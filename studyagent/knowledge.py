"""Scoped document admission, pgvector retrieval and evidence-bound answers.

Uploaded bytes and model text are data. All database scope checks happen here;
none of the model's identifiers or validation judgments authorize an operation.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx
import pymupdf
from psycopg.types.json import Jsonb

from .db import DomainError, uid
from .providers import ProviderError
from .schemas import AgentDecision, Answer, EvidenceCheck, GraphDraft, MaterialCheck


def _vector(values):
    if (len(values) != 768 or not all(type(x) in (int, float) and math.isfinite(x) for x in values)
            or not any(values)):
        raise ProviderError('嵌入结果必须为 768 维有限且非零向量。')
    return json.dumps(values)


def _pages(filename, content):
    suffix = Path(filename).suffix.lower()
    if suffix == '.pdf':
        try:
            with pymupdf.open(stream=content, filetype='pdf') as document:
                if document.is_encrypted:
                    raise ValueError('加密 PDF 无法读取，请上传未加密版本。')
                if not 1 <= len(document) <= 100:
                    raise ValueError('原型仅接纳 1–100 页 PDF。')
                pages = [{'page': i + 1, 'text': p.get_text('text', sort=True).replace('\x00', '')}
                         for i, p in enumerate(document)]
        except (RuntimeError, pymupdf.FileDataError) as exc:
            raise ValueError('PDF 无法解析，可能已损坏或格式不正确。') from exc
    elif suffix in {'.txt', '.md'}:
        try:
            pages = [{'page': 1, 'text': content.decode('utf-8-sig').replace('\x00', '')}]
        except UnicodeDecodeError as exc:
            raise ValueError('文本文件必须使用 UTF-8 编码。') from exc
    else:
        raise ValueError('仅支持 PDF、TXT 和 Markdown 文件。')
    chars = sum(len(re.sub(r'\s', '', p['text'])) for p in pages)
    if chars < 40:
        raise ValueError('可用文本不足 40 个非空白字符；扫描 PDF 请先做 OCR。')
    if chars > 500_000:
        raise ValueError('提取文本超过 50 万字符，请拆成更小的材料。')
    return pages


def _chunks(document_id, pages):
    chunks = []
    for page in pages:
        text = page['text'].strip()
        section = next((line.lstrip('# ').strip()[:120] for line in text.splitlines() if line.strip()), '')
        for offset in range(0, len(text), 850):
            part = text[offset:offset + 1000].strip()
            if part:
                chunks.append({'id': uid(), 'document_id': document_id,
                               'page': page['page'], 'section': section, 'text': part})
            if offset + 1000 >= len(text):
                break
    return chunks


def _sample(items, maximum):
    """Evenly sample across the document, including its first and last pages."""
    if len(items) <= maximum:
        return items
    return [items[round(i * (len(items) - 1) / (maximum - 1))] for i in range(maximum)]


class Knowledge:
    def __init__(self, db, provider, settings):
        self.db, self.provider, self.settings = db, provider, settings
        self.embedding_model = 'fake' if settings.provider == 'fake' else settings.embedding_model

    @staticmethod
    def _scope(space):
        return {k: space[k] for k in ('id', 'name', 'kind', 'topic')}

    def _material_check(self, space, pages, source_url, filename, exclude_id=None):
        existing = self.db.all(
            'SELECT d.id,d.filename,c.text FROM space_documents sd JOIN documents d ON d.id=sd.document_id '
            'JOIN LATERAL (SELECT text FROM chunks WHERE document_id=d.id ORDER BY page,id LIMIT 1) c ON true '
            "WHERE sd.space_id=%s AND sd.status='accepted' AND d.id<>%s ORDER BY d.created_at DESC LIMIT 12",
            (space['id'], exclude_id or ''))
        sampled = [{'page': p['page'], 'text': p['text'][:800]} for p in _sample(pages, 8)]
        payload = {'space': self._scope(space), 'scope': space['topic'], 'topic': space['topic'],
                   'filename': filename, 'source_url': source_url, 'pages': sampled,
                   'text': '\n'.join(p['text'] for p in sampled),
                   'existing_evidence': [{**e, 'text': e['text'][:500]} for e in existing],
                   'validation_limits': '抽样筛选不保证事实正确；来源网址仅是上传者声明，尚未独立核实。'}
        check = self.provider.complete('validate_material', payload, MaterialCheck)
        if check['conflicts']:
            check['status'] = 'conflict'
        elif check['status'] == 'accepted' and not (check['relevant'] and check['credible']):
            check['status'] = 'uncertain'
            check['reason'] += ' 未同时通过相关性和可信度检查。'
        self.db.event(space['id'], 'material_validation', {
            'filename': filename, 'source_url': source_url, 'check': check,
            'sampled_pages': [p['page'] for p in sampled],
            'compared_document_ids': [e['id'] for e in existing], 'provider': self.settings.provider})
        return check

    def _document(self, space_id, document_id):
        self.db.space(space_id)
        row = self.db.one(
            'SELECT d.*,sd.status AS admission_status,sd.reason AS admission_reason FROM documents d '
            'JOIN space_documents sd ON sd.document_id=d.id WHERE sd.space_id=%s AND d.id=%s',
            (space_id, document_id))
        if not row:
            raise DomainError('材料不属于当前空间。', 404)
        row['status'], row['reason'] = row.pop('admission_status'), row.pop('admission_reason')
        return row

    def ingest(self, space_id, filename, content: bytes, source_url=''):
        space = self.db.space(space_id)
        filename = Path(filename.replace('\\', '/')).name[:180] or 'upload'
        if source_url:
            url = urlparse(source_url)
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
                raise DomainError('来源网址必须是无凭据的 HTTP(S) URL。')
            if len(source_url) > 2000:
                raise DomainError('来源网址过长。')
        with self.db.lock('ingest:' + space_id) as conn:
            doc_id, digest = uid(), hashlib.sha256(content).hexdigest()
            status, reason, pages, chunks = 'pending', '', [], []
            if not content or len(content) > self.settings.upload_max_bytes:
                status, reason = 'rejected', '文件为空或超过 20 MB 上传限制。'
            else:
                try:
                    pages = _pages(filename, content)
                except ValueError as exc:
                    status, reason = 'rejected', str(exc)
            if status == 'pending':
                duplicate = conn.execute(
                    'SELECT d.id FROM documents d JOIN space_documents sd ON sd.document_id=d.id '
                    "WHERE sd.space_id=%s AND d.sha256=%s AND sd.status='accepted' LIMIT 1", (space_id, digest)).fetchone()
                if duplicate:
                    status, reason = 'duplicate', f"内容与已接纳材料 {duplicate['id']} 完全相同。"
                elif space['kind'] == 'focus' and conn.execute(
                    "SELECT 1 FROM space_documents WHERE space_id=%s AND status='accepted'", (space_id,)).fetchone():
                    status, reason = 'rejected', 'Focus Space 只能接纳一份材料；请新建 Focus 或使用 Course。'
            if status == 'pending':
                try:
                    check = self._material_check(space, pages, source_url, filename)
                    status, reason = check['status'], check['reason']
                    if status == 'accepted':
                        chunks = _chunks(doc_id, pages)
                        for start in range(0, len(chunks), 16):
                            batch = chunks[start:start + 16]
                            embeddings = self.provider.embed([c['text'] for c in batch])
                            if len(embeddings) != len(batch):
                                raise ProviderError('嵌入结果数量与分块数量不一致。')
                            for chunk, vector in zip(batch, embeddings):
                                chunk['embedding'] = _vector(vector)
                except ProviderError as exc:
                    status, reason, chunks = 'uncertain', str(exc), []
            uploads = Path(self.settings.runtime_dir) / 'uploads'
            uploads.mkdir(parents=True, exist_ok=True)
            path = uploads / (doc_id + Path(filename).suffix.lower())
            file_path = ''
            if content and len(content) <= self.settings.upload_max_bytes:
                path.write_bytes(content)
                file_path = str(path.resolve())
            with conn.transaction():
                conn.execute('INSERT INTO documents(id,origin_space_id,filename,sha256,file_path,pages,source_url,status,reason) '
                             'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                             (doc_id, space_id, filename, digest, file_path, Jsonb(pages), source_url, status, reason))
                conn.execute('INSERT INTO space_documents(space_id,document_id,status,reason) VALUES (%s,%s,%s,%s)',
                             (space_id, doc_id, status, reason))
                if status == 'accepted':
                    for chunk in chunks:
                        conn.execute('INSERT INTO chunks(id,document_id,page,section,text,embedding,embedding_model) '
                                     'VALUES (%s,%s,%s,%s,%s,%s::vector,%s)',
                                     (chunk['id'], doc_id, chunk['page'], chunk['section'], chunk['text'],
                                      chunk['embedding'], self.embedding_model))
            self.db.event(space_id, 'upload_result', {
                'document_id': doc_id, 'status': status, 'reason': reason,
                'pages': len(pages), 'chunks': len(chunks) if status == 'accepted' else 0,
                'embedding_model': self.embedding_model})
            if status == 'accepted':
                self._update_graph(space_id, doc_id)
            return self._document(space_id, doc_id)

    def admit(self, target_space_id, source_space_id, document_id):
        target, source = self.db.space(target_space_id), self.db.space(source_space_id)
        if target['kind'] != 'course' or source['kind'] != 'focus' or target_space_id == source_space_id:
            raise DomainError('仅支持将 Focus 材料接纳到 Course。')
        document = self._document(source_space_id, document_id)
        if document['status'] != 'accepted' or document['origin_space_id'] != source_space_id:
            raise DomainError('只有来源 Focus 中已接纳的原始材料可以加入课程。', 409)
        with self.db.lock('ingest:' + target_space_id) as conn:
            current = conn.execute('SELECT status FROM space_documents WHERE space_id=%s AND document_id=%s',
                                   (target_space_id, document_id)).fetchone()
            if current and current['status'] == 'accepted':
                return self._document(target_space_id, document_id)
            duplicate = conn.execute(
                'SELECT d.id FROM documents d JOIN space_documents sd ON sd.document_id=d.id '
                "WHERE sd.space_id=%s AND sd.status='accepted' AND d.sha256=%s", (target_space_id, document['sha256'])).fetchone()
            if duplicate:
                status, reason = 'duplicate', f"课程已有相同内容：{duplicate['id']}。"
            else:
                try:
                    check = self._material_check(target, document['pages'], document['source_url'], document['filename'])
                    status, reason = check['status'], check['reason']
                except ProviderError as exc:
                    status, reason = 'uncertain', str(exc)
            conn.execute('INSERT INTO space_documents(space_id,document_id,status,reason) VALUES (%s,%s,%s,%s) '
                         'ON CONFLICT(space_id,document_id) DO UPDATE SET status=EXCLUDED.status,reason=EXCLUDED.reason',
                         (target_space_id, document_id, status, reason))
            self.db.event(target_space_id, 'admission_result', {'document_id': document_id,
                          'source_space_id': source_space_id, 'status': status, 'reason': reason})
            if status == 'accepted':
                self._update_graph(target_space_id, document_id)
            return self._document(target_space_id, document_id)

    def _update_graph(self, space_id, document_id):
        space = self.db.space(space_id)
        evidence = self.db.all('SELECT id,text,page FROM chunks WHERE document_id=%s ORDER BY page,id', (document_id,))
        evidence = _sample(evidence, 16)
        try:
            draft = self.provider.complete('extract_graph', {
                'space': self._scope(space), 'scope': space['topic'], 'topic': space['topic'],
                'evidence': evidence, 'existing_concepts': [n['name'] for n in space['graph'].get('nodes', [])]}, GraphDraft)
        except ProviderError as exc:
            self.db.event(space_id, 'graph_pending', {'document_id': document_id, 'reason': str(exc)})
            return
        visible = getattr(self.provider, 'last_evidence', None)
        actual_ids = {e.get('id', e.get('evidence_id')) for e in (evidence if visible is None else visible)}
        graph = space['graph']
        nodes = {n['id']: n for n in graph.get('nodes', [])}
        names = {n['name'].casefold(): n['id'] for n in nodes.values()}
        with self.db.connect() as conn, conn.transaction():
            for concept in draft['concepts'][:30]:
                name = re.sub(r'\s+', ' ', concept['name']).strip()[:100]
                ids = list(dict.fromkeys(concept['evidence_ids']))
                if not name or not ids or not set(ids) <= actual_ids:
                    self.db.event(space_id, 'graph_concept_excluded', {'name': name, 'reason': '缺少本轮真实证据'})
                    continue
                cid = names.get(name.casefold()) or str(uuid5(NAMESPACE_URL, space_id + ':' + name.casefold()))
                names[name.casefold()] = cid
                old_ids = nodes.get(cid, {}).get('evidence_ids', [])
                ids = list(dict.fromkeys(old_ids + ids))
                # An existing name/id stays stable when later material adds evidence.
                name = nodes.get(cid, {}).get('name', name)
                nodes[cid] = {'id': cid, 'name': name, 'description': concept['description'][:2000],
                              'evidence_ids': ids, 'status': 'accepted'}
                conn.execute('INSERT INTO concepts(id,space_id,name,description,evidence_ids) VALUES (%s,%s,%s,%s,%s) '
                             'ON CONFLICT(id) DO UPDATE SET description=EXCLUDED.description,evidence_ids=EXCLUDED.evidence_ids',
                             (cid, space_id, name, concept['description'][:2000], Jsonb(ids)))
            edges = list(graph.get('edges', []))
            adjacency = {}
            for edge in edges:
                if edge.get('status') == 'accepted':
                    adjacency.setdefault(edge['source'], set()).add(edge['target'])

            def reachable(start, end):
                pending, visited = [start], set()
                while pending:
                    node = pending.pop()
                    if node == end:
                        return True
                    if node not in visited:
                        visited.add(node)
                        pending.extend(adjacency.get(node, ()))
                return False

            for edge in draft['edges'][:60]:
                source = names.get(edge['source'].casefold(), edge['source'])
                target = names.get(edge['target'].casefold(), edge['target'])
                ids = list(dict.fromkeys(edge['evidence_ids']))
                reason = ''
                if source not in nodes or target not in nodes or not ids or not set(ids) <= actual_ids:
                    reason = '缺少已接纳概念或本轮证据，待复核。'
                elif reachable(target, source):
                    reason = '该前置关系形成循环，待复核。'
                status = 'pending' if reason else 'accepted'
                if any(e['source'] == source and e['target'] == target and e.get('status') == status for e in edges):
                    continue
                edges.append({'source': source, 'target': target, 'evidence_ids': ids,
                              'status': status, 'reason': reason})
                if status == 'accepted':
                    adjacency.setdefault(source, set()).add(target)
            graph = {'nodes': list(nodes.values()), 'edges': edges}
            conn.execute('UPDATE spaces SET graph=%s WHERE id=%s', (Jsonb(graph), space_id))
        self.db.event(space_id, 'graph_update', {'document_id': document_id, 'nodes': len(nodes),
                      'accepted_edges': sum(e.get('status') == 'accepted' for e in edges),
                      'pending_edges': sum(e.get('status') == 'pending' for e in edges)})

    def concepts(self, space_id):
        self.db.space(space_id)
        rows = self.db.all('SELECT c.*,m.score,COALESCE(m.attempts,0) AS attempts,COALESCE(m.streak,0) AS streak,'
                           "COALESCE(m.errors,'[]') AS errors FROM concepts c LEFT JOIN mastery m "
                           'ON m.space_id=c.space_id AND m.concept_id=c.id WHERE c.space_id=%s ORDER BY c.name', (space_id,))
        for row in rows:
            row['mastery'] = {key: row.pop(key) for key in ('score', 'attempts', 'streak', 'errors')}
        return rows

    def retrieve(self, space_id, query, k=6):
        self.db.space(space_id)
        if not isinstance(query, str) or not query.strip() or len(query) > 7000:
            raise DomainError('检索问题必须为 1–7000 字符。')
        if type(k) is not int or not 1 <= k <= 12:
            raise DomainError('检索条数须介于 1 和 12。')
        started = time.monotonic()
        vector = _vector(self.provider.embed([query])[0])
        rows = self.db.all(
            'WITH ranked AS (SELECT c.id,c.document_id,c.page,c.section,c.text,d.filename,d.source_url AS url,'
            'c.embedding <=> %s::vector AS distance, '
            'row_number() OVER(PARTITION BY c.document_id ORDER BY c.embedding <=> %s::vector,c.id) AS doc_rank '
            'FROM chunks c JOIN documents d ON d.id=c.document_id JOIN space_documents sd ON sd.document_id=d.id '
            "WHERE sd.space_id=%s AND sd.status='accepted' AND c.embedding_model=%s) "
            'SELECT * FROM ranked ORDER BY (doc_rank=1) DESC,distance,id LIMIT %s',
            (vector, vector, space_id, self.embedding_model, k))
        for row in rows:
            row['evidence_id'] = row['id']
            row.pop('doc_rank', None)
        self.db.event(space_id, 'retrieval', {'query': query, 'evidence_ids': [r['id'] for r in rows],
                      'embedding_model': self.embedding_model, 'k': k,
                      'latency_ms': round((time.monotonic() - started) * 1000, 2)})
        return rows

    def _check_evidence(self, space, message, evidence):
        result = self.provider.complete('evidence_check', {
            'space': self._scope(space), 'scope': space['topic'], 'topic': space['topic'],
            'question': message, 'message': message, 'evidence': evidence}, EvidenceCheck)
        if not evidence or result['conflicts']:
            result['sufficient'] = False
        self.db.event(space['id'], 'retrieval_validation', {'check': result, 'evidence_ids': [e['id'] for e in evidence]})
        return result

    def _fetch_arxiv(self, client, url, params=None):
        # Only hardcoded service URLs and validated arXiv IDs reach this method.
        for attempt in range(3):
            try:
                with client.stream('GET', url, params=params) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for block in response.iter_bytes():
                        content.extend(block)
                        if len(content) > 1_000_000:
                            raise ValueError('网络来源响应过大。')
                    return bytes(content)
            except (httpx.TimeoutException, httpx.NetworkError):
                if attempt == 2:
                    raise
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
            time.sleep(3)
        raise ValueError('网络来源请求未完成。')

    def _search(self, space, message):
        if self.settings.search_provider == 'disabled':
            self.db.event(space['id'], 'web_search', {'status': 'disabled', 'query': message})
            return []
        # Phrase query prevents the user text becoming arXiv query operators.
        phrase = re.sub(r'[^\w\s\-]', ' ', message, flags=re.UNICODE)[:250].strip()
        if not phrase:
            return []
        evidence = []
        try:
            with httpx.Client(timeout=10, follow_redirects=False,
                              headers={'User-Agent': 'StudyAgent-course-prototype/1.0'}) as client:
                feed = self._fetch_arxiv(client, 'https://export.arxiv.org/api/query',
                                        {'search_query': f'all:"{phrase}"', 'start': 0, 'max_results': 2})
                root = ET.fromstring(feed)
                namespace = {'a': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('a:entry', namespace)[:2]:
                    raw_id = entry.findtext('a:id', '', namespace)
                    arxiv_id = raw_id.rsplit('/', 1)[-1]
                    if not re.fullmatch(r'\d{4}\.\d{4,5}(?:v\d+)?', arxiv_id):
                        continue
                    url = 'https://arxiv.org/abs/' + arxiv_id
                    time.sleep(3)  # arXiv requests are serialized with a courteous gap.
                    html = self._fetch_arxiv(client, url)
                    soup = BeautifulSoup(html, 'html.parser')
                    abstract = soup.select_one('blockquote.abstract')
                    title = soup.select_one('h1.title')
                    if not abstract or not title:
                        continue
                    text = abstract.get_text(' ', strip=True)[:6000]
                    title = title.get_text(' ', strip=True).removeprefix('Title:').strip()
                    check = self.provider.complete('validate_material', {
                        'space': self._scope(space), 'scope': space['topic'], 'topic': space['topic'],
                        'filename': title, 'source_url': url, 'text': text,
                        'source_type': 'arXiv abstract page, preprint is not automatically peer reviewed',
                        'purpose': 'temporary web evidence for question', 'question': message,
                        'existing_evidence': []}, MaterialCheck)
                    passed = check['status'] == 'accepted' and check['relevant'] and check['credible'] and not check['conflicts']
                    self.db.event(space['id'], 'web_validation', {'url': url, 'check': check, 'usable': passed})
                    if passed:
                        eid = 'web:' + hashlib.sha256((url + text).encode()).hexdigest()[:24]
                        evidence.append({'id': eid, 'evidence_id': eid, 'document_id': None, 'page': None,
                                         'section': 'Abstract', 'text': text, 'filename': title, 'url': url})
            self.db.event(space['id'], 'web_search', {'status': 'completed', 'query': message,
                          'evidence_ids': [e['id'] for e in evidence], 'temporary': True})
        except (httpx.HTTPError, ET.ParseError, ValueError, ProviderError):
            self.db.event(space['id'], 'web_search', {'status': 'unavailable', 'query': message,
                          'reason': '网络搜索或来源验证未完成，重试已受限。', 'temporary': True})
        return evidence

    def answer(self, space_id, message, history=None, state=None, baseline=False):
        space = self.db.space(space_id)
        history, state = history or [], state or {}
        if state.get('space_id') not in {None, space_id}:
            raise DomainError('学习状态不属于当前空间。', 409)
        for key in ('concept_id', 'current_concept_id', 'goal_concept_id'):
            if state.get(key):
                self.db.concept(space_id, state[key])
        query = message
        if len(message) < 80:
            prior = next((m.get('content', '') for m in reversed(history) if m.get('role') == 'user'), '')
            if isinstance(prior, str) and prior:
                query = prior[-300:] + '\n追问：' + message
        evidence = self.retrieve(space_id, query)
        check = self._check_evidence(space, message, evidence)

        def response(answer, citations, gap, action, reason):
            decision = AgentDecision(action=action, space_id=space_id, concept_id=state.get('concept_id'),
                                     evidence_ids=[c['evidence_id'] for c in citations], reason=reason[:600]).model_dump()
            self.db.event(space_id, 'chat_decision', {'decision': decision, 'baseline': baseline,
                          'citation_ids': [c['evidence_id'] for c in citations], 'gap': gap})
            return {'answer': answer, 'citations': citations, 'gap': gap,
                    'decision': decision, 'provider': self.settings.provider}

        if not check['in_scope']:
            return response('这个问题与当前空间的材料范围不匹配。请切换空间或明确希望关联的课程概念。', [],
                            '需要明确学习范围。', 'clarify', check['reason'])
        if not check['sufficient']:
            evidence += self._search(space, message)
            check = self._check_evidence(space, message, evidence)
        if not check['sufficient'] or not check['in_scope']:
            gap = '；'.join(check['missing'] + check['conflicts']) or '当前证据不能充分支持回答。'
            return response('证据仍不足：' + gap + ' 请补充材料或细化问题。', [], gap, 'clarify', check['reason'])
        generated = self.provider.complete('answer', {
            'space': self._scope(space), 'scope': space['topic'], 'topic': space['topic'],
            'question': message, 'message': message, 'history': history, 'state': {} if baseline else state,
            'evidence': evidence}, Answer)
        # The generation call may have shortened evidence to fit its final input.
        # Bind citations to that exact visible excerpt, not the pre-budget candidate.
        original = {e['id']: e for e in evidence}
        visible = getattr(self.provider, 'last_evidence', None)
        available = original if visible is None else {
            e.get('id', e.get('evidence_id')): dict(original[e.get('id', e.get('evidence_id'))], text=e['text'])
            for e in visible if e.get('id', e.get('evidence_id')) in original
        }
        citations, seen = [], set()
        for citation in generated['citations']:
            eid, quote = citation['evidence_id'], citation['quote']
            if eid not in available or not quote.strip() or quote not in available[eid]['text']:
                self.db.event(space_id, 'citation_validation', {'status': 'rejected', 'evidence_id': eid,
                              'reason': '引用 ID 或逐字片段不在本轮证据中。'})
                return response('生成的引用未通过核对，本次回答未采纳。请重试或补充材料。', [],
                                '引用验证失败。', 'clarify', '拒绝引用未召回或不匹配的片段。')
            if eid not in seen:
                citations.append({**available[eid], 'quote': quote})
                seen.add(eid)
        if not citations and not generated['gap']:
            return response('回答没有提供可核对的来源，本次回答未采纳。', [], '缺少证据引用。',
                            'clarify', '有依据的课程回答必须绑定本轮来源。')
        support = self.provider.complete('evidence_check', {
            'space': self._scope(space), 'scope': space['topic'], 'question': message,
            'candidate_answer': generated['answer'], 'evidence': citations,
        }, EvidenceCheck)
        self.db.event(space_id, 'answer_validation', {'check': support, 'evidence_ids': list(seen)})
        if not support['sufficient'] or not support['in_scope'] or support['conflicts']:
            gap = '；'.join(support['missing'] + support['conflicts']) or '生成主张未通过证据支持检查。'
            return response('回答的证据支持尚未确认：' + gap, [], gap, 'clarify', support['reason'])
        self.db.event(space_id, 'citation_validation', {'status': 'passed', 'evidence_ids': list(seen),
                      'note': 'ID 与逐字片段核对；不等同于已证明所有生成主张正确。'})
        return response(generated['answer'], citations, generated['gap'], 'answer',
                        '根据已检索且通过充分性检查的证据回答；General Chat 本轮结束。')
