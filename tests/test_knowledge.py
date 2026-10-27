"""Knowledge integration tests: real isolated PostgreSQL spaces, deterministic model double."""
from uuid import uuid4

import pytest

from studyagent.config import Settings
from studyagent.db import Database, DomainError


class ModelDouble:
    def __init__(self):
        self.calls = []
        self.material_status = 'accepted'
        self.sufficient = True
        self.in_scope = True
        self.bad_citation = False
        self.cycle = False

    def embed(self, texts):
        return [[1.0] + [0.0] * 767 for _ in texts]

    def complete(self, task, payload, schema):
        self.calls.append((task, payload))
        if task == 'validate_material':
            value = dict(status=self.material_status, reason='Deterministic test judgment',
                         relevant=True, credible=True, conflicts=[])
        elif task == 'extract_graph':
            evidence = payload['evidence'][0]['id']
            value = {'concepts': [
                {'name': name, 'description': name + ' description', 'evidence_ids': [evidence]}
                for name in ['Gradient', 'Optimization']],
                'edges': [{'source': 'Gradient', 'target': 'Optimization', 'evidence_ids': [evidence]}]}
            if self.cycle:
                value['edges'].extend([
                    {'source': 'Optimization', 'target': 'Gradient', 'evidence_ids': [evidence]},
                    {'source': 'Gradient', 'target': 'Ghost', 'evidence_ids': ['invented']},
                ])
        elif task == 'evidence_check':
            value = dict(sufficient=self.sufficient, in_scope=self.in_scope,
                         missing=[] if self.sufficient else ['missing fact'], conflicts=[], reason='test')
        elif task == 'answer':
            value = dict(answer='Answer from retrieved evidence.', gap='', citations=[
                {'evidence_id': 'invented' if self.bad_citation else e['id'], 'quote': e['text'][:30]}
                for e in payload['evidence']])
        else:
            raise AssertionError(task)
        return schema.model_validate(value).model_dump()


@pytest.fixture
def knowledge(tmp_path):
    from studyagent.knowledge import Knowledge

    settings = Settings(STUDYAGENT_PROVIDER='fake', search_provider='disabled', runtime_dir=tmp_path,
                        user_id='test-knowledge-' + uuid4().hex)
    db = Database(settings)
    db.migrate()
    model = ModelDouble()
    return Knowledge(db, model, settings)


def space(k, kind='course'):
    return k.db.create_space('Knowledge test ' + uuid4().hex[:8], kind, 'machine learning and gradients')['id']


def material(extra=''):
    return ('# Gradient\nGradient points toward the greatest local rate of increase. '
            'Gradient descent updates parameters in the negative gradient direction. '
            'Optimization minimizes a differentiable objective. ' + extra).encode()


def test_ingestion_preserves_page_sources_and_unknown_mastery(knowledge):
    k, sid = knowledge, space(knowledge)
    doc = k.ingest(sid, '../../gradient.md', material())
    assert doc['status'] == 'accepted'
    assert doc['filename'] == 'gradient.md'
    hits = k.retrieve(sid, 'gradient')
    assert hits and hits[0]['document_id'] == doc['id'] and hits[0]['page'] == 1
    assert hits[0]['evidence_id'] == hits[0]['id']
    assert all(c['mastery']['score'] is None and c['mastery']['attempts'] == 0 for c in k.concepts(sid))


def test_bad_files_duplicates_and_conflicts_never_enter_retrieval(knowledge):
    k, sid = knowledge, space(knowledge)
    invalid = k.ingest(sid, 'broken.pdf', b'not a pdf')
    assert invalid['status'] == 'rejected'
    accepted = k.ingest(sid, 'good.txt', material())
    duplicate = k.ingest(sid, 'copy.txt', material())
    assert duplicate['status'] == 'duplicate'
    k.provider.material_status = 'conflict'
    conflict = k.ingest(sid, 'conflict.txt', material('Conflicting statement.'))
    assert conflict['status'] == 'conflict'
    assert {e['document_id'] for e in k.retrieve(sid, 'gradient')} == {accepted['id']}


def test_focus_admission_keeps_shared_document_and_independent_mastery(knowledge):
    k = knowledge
    focus, course = space(k, 'focus'), space(k)
    doc = k.ingest(focus, 'one.txt', material())
    assert k.ingest(focus, 'two.txt', material('Second.'))['status'] == 'rejected'
    admitted = k.admit(course, focus, doc['id'])
    assert admitted['id'] == doc['id'] and admitted['status'] == 'accepted'
    assert k.concepts(course)[0]['id'] != k.concepts(focus)[0]['id']
    assert k.concepts(course)[0]['mastery']['attempts'] == 0
    with pytest.raises(DomainError):
        k.admit(space(k), course, doc['id'])


def test_cross_space_identifiers_and_other_owners_are_rejected(knowledge):
    k = knowledge
    sid, elsewhere = space(k, 'focus'), space(k)
    doc = k.ingest(sid, 'one.txt', material())
    with pytest.raises(DomainError):
        k.admit(elsewhere, space(k, 'focus'), doc['id'])
    k.db.execute('UPDATE spaces SET owner_id=%s WHERE id=%s', ('another-user', sid))
    with pytest.raises(DomainError):
        k.retrieve(sid, 'gradient')


def test_cycle_and_unsupported_edges_are_pending(knowledge):
    k, sid = knowledge, space(knowledge)
    k.provider.cycle = True
    k.ingest(sid, 'one.txt', material())
    edges = k.db.space(sid)['graph']['edges']
    assert len([e for e in edges if e['status'] == 'accepted']) == 1
    assert len([e for e in edges if e['status'] == 'pending']) == 2


def test_retrieval_diversity_and_citations_use_actual_sources(knowledge):
    k, sid = knowledge, space(knowledge)
    one = k.ingest(sid, 'one.txt', material('Long passage. ' * 300))
    two = k.ingest(sid, 'two.txt', material('Second source.'))
    result = k.answer(sid, 'What is gradient descent?')
    assert {c['document_id'] for c in result['citations']} == {one['id'], two['id']}
    assert all(c['quote'] in c['text'] for c in result['citations'])
    assert result['decision']['action'] == 'answer'
    k.provider.bad_citation = True
    invalid = k.answer(sid, 'What is gradient?')
    assert invalid['citations'] == [] and invalid['gap']


def test_insufficient_evidence_and_out_of_scope_stop_without_fabrication(knowledge):
    k, sid = knowledge, space(knowledge)
    k.ingest(sid, 'one.txt', material())
    k.provider.sufficient = False
    result = k.answer(sid, 'Uncovered fact?')
    assert result['gap'] and not result['citations']
    k.provider.in_scope = False
    result = k.answer(sid, 'What is the weather?')
    assert result['decision']['action'] == 'clarify'


def test_embedding_modes_never_mix(knowledge):
    k, sid = knowledge, space(knowledge)
    doc = k.ingest(sid, 'one.txt', material())
    k.db.execute('UPDATE chunks SET embedding_model=%s WHERE document_id=%s', ('other-model', doc['id']))
    assert k.retrieve(sid, 'gradient') == []


def test_citations_cannot_refer_to_provider_omitted_text(knowledge):
    k, sid = knowledge, space(knowledge)
    k.ingest(sid, 'one.txt', material())
    complete = k.provider.complete

    def truncated(task, payload, schema):
        result = complete(task, payload, schema)
        if task == 'answer':
            k.provider.last_evidence = [{**payload['evidence'][0], 'text': payload['evidence'][0]['text'][:5]}]
        return result

    k.provider.complete = truncated
    result = k.answer(sid, 'What is gradient?')
    assert result['gap'] and not result['citations']


def test_unsupported_answer_claims_are_withheld(knowledge):
    k, sid = knowledge, space(knowledge)
    k.ingest(sid, 'one.txt', material())
    complete = k.provider.complete

    def checked(task, payload, schema):
        result = complete(task, payload, schema)
        if task == 'evidence_check' and payload.get('candidate_answer'):
            result.update(sufficient=False, missing=['answer claim lacks evidence'])
        return result

    k.provider.complete = checked
    result = k.answer(sid, 'What is gradient?')
    assert result['gap'] and not result['citations']


def test_pdf_actual_page_numbers(knowledge):
    import pymupdf

    pdf = pymupdf.open()
    for i in range(2):
        page = pdf.new_page()
        page.insert_text((40, 60), f'Page {i+1}: Gradient descent minimizes the objective. ' * 2)
    k, sid = knowledge, space(knowledge)
    doc = k.ingest(sid, 'two-pages.pdf', pdf.tobytes())
    pdf.close()
    assert doc['status'] == 'accepted'
    assert {c['page'] for c in k.retrieve(sid, 'gradient')} == {1, 2}


def test_web_evidence_is_verified_temporary_and_uses_fixed_hosts(knowledge, monkeypatch):
    import httpx
    from studyagent import knowledge as module

    k, sid = knowledge, space(knowledge)
    k.settings.search_provider = 'arxiv'
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom">
              <entry><id>https://arxiv.org/abs/1706.03762</id></entry>
              <entry><id>http://127.0.0.1/private</id></entry></feed>''')
        assert str(request.url) == 'https://arxiv.org/abs/1706.03762'
        return httpx.Response(200, text='<h1 class="title">Title: Verified page</h1>'
                              '<blockquote class="abstract">Attention is a weighted sum of values.</blockquote>')

    original = httpx.Client
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    result = k._search(k.db.space(sid), 'attention')
    assert len(result) == 1 and len(requests) == 2
    assert result[0]['url'] == 'https://arxiv.org/abs/1706.03762'
    assert k.db.one('SELECT count(*) AS n FROM space_documents WHERE space_id=%s', (sid,))['n'] == 0
    assert k.db.one('SELECT count(*) AS n FROM memories WHERE source_space_id=%s', (sid,))['n'] == 0
    assert k.db.one("SELECT count(*) AS n FROM events WHERE space_id=%s AND kind='web_validation'", (sid,))['n'] == 1


def test_web_timeout_is_bounded_and_reported(knowledge, monkeypatch):
    import httpx
    from studyagent import knowledge as module

    k, sid = knowledge, space(knowledge)
    k.settings.search_provider = 'arxiv'
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('untrusted remote details', request=request)

    original = httpx.Client
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert k._search(k.db.space(sid), 'attention') == []
    assert len(calls) == 3
    event = k.db.one("SELECT payload FROM events WHERE space_id=%s AND kind='web_search' ORDER BY id DESC LIMIT 1", (sid,))
    assert event['payload']['status'] == 'unavailable'

def test_graph_rejects_evidence_omitted_from_final_model_input(knowledge):
    k, sid = knowledge, space(knowledge)
    complete = k.provider.complete
    def omitted(task, payload, schema):
        result = complete(task, payload, schema)
        if task == 'extract_graph':
            k.provider.last_evidence = []
        return result
    k.provider.complete = omitted
    k.ingest(sid, 'one.txt', material())
    assert k.concepts(sid) == []
