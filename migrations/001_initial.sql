CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS spaces (
 id text PRIMARY KEY, owner_id text NOT NULL, name text NOT NULL, kind text NOT NULL CHECK(kind IN ('course','focus')),
 topic text NOT NULL, graph jsonb NOT NULL DEFAULT '{"nodes":[],"edges":[]}', created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS documents (
 id text PRIMARY KEY, origin_space_id text NOT NULL REFERENCES spaces(id), filename text NOT NULL,
 sha256 text NOT NULL, file_path text NOT NULL, pages jsonb NOT NULL DEFAULT '[]', source_url text NOT NULL DEFAULT '',
 status text NOT NULL, reason text NOT NULL DEFAULT '', created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS space_documents (
 space_id text REFERENCES spaces(id), document_id text REFERENCES documents(id), status text NOT NULL, reason text NOT NULL DEFAULT '',
 PRIMARY KEY(space_id,document_id));
CREATE TABLE IF NOT EXISTS chunks (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES documents(id), page integer NOT NULL,
 section text NOT NULL DEFAULT '', text text NOT NULL, embedding vector(768) NOT NULL, embedding_model text NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_doc_idx ON chunks(document_id);
CREATE TABLE IF NOT EXISTS concepts (
 id text PRIMARY KEY, space_id text NOT NULL REFERENCES spaces(id), name text NOT NULL, description text NOT NULL DEFAULT '',
 evidence_ids jsonb NOT NULL DEFAULT '[]', UNIQUE(space_id,name), UNIQUE(id,space_id));
CREATE TABLE IF NOT EXISTS sessions (
 id text PRIMARY KEY, space_id text NOT NULL REFERENCES spaces(id), thread_id text NOT NULL UNIQUE,
 goal_concept_id text NOT NULL, current_concept_id text NOT NULL, status text NOT NULL,
 step integer NOT NULL DEFAULT 0, state jsonb NOT NULL DEFAULT '{}', created_at timestamptz DEFAULT now(),
 UNIQUE(id,space_id), FOREIGN KEY(goal_concept_id,space_id) REFERENCES concepts(id,space_id),
 FOREIGN KEY(current_concept_id,space_id) REFERENCES concepts(id,space_id));
CREATE TABLE IF NOT EXISTS quizzes (
 id text PRIMARY KEY, session_id text NOT NULL, space_id text NOT NULL, concept_id text NOT NULL,
 sequence integer NOT NULL, question text NOT NULL, options jsonb NOT NULL,
 correct_index integer NOT NULL, rubric text NOT NULL, answer_explanation text NOT NULL,
 evidence_ids jsonb NOT NULL, mode text NOT NULL, status text NOT NULL DEFAULT 'active',
 created_at timestamptz DEFAULT now(), UNIQUE(session_id,sequence), UNIQUE(id,session_id,space_id),
 FOREIGN KEY(session_id,space_id) REFERENCES sessions(id,space_id), FOREIGN KEY(concept_id,space_id) REFERENCES concepts(id,space_id));
CREATE TABLE IF NOT EXISTS attempts (
 id text PRIMARY KEY, submission_id text NOT NULL, quiz_id text NOT NULL UNIQUE, session_id text NOT NULL, space_id text NOT NULL,
 answer text NOT NULL, correct boolean NOT NULL, score double precision NOT NULL CHECK(score>=0 AND score<=1), feedback text NOT NULL,
 created_at timestamptz DEFAULT now(), UNIQUE(session_id,submission_id),
 FOREIGN KEY(quiz_id,session_id,space_id) REFERENCES quizzes(id,session_id,space_id));
CREATE TABLE IF NOT EXISTS mastery (
 space_id text NOT NULL, concept_id text NOT NULL, score double precision,
 attempts integer NOT NULL DEFAULT 0, streak integer NOT NULL DEFAULT 0, errors jsonb NOT NULL DEFAULT '[]',
 PRIMARY KEY(space_id,concept_id), FOREIGN KEY(concept_id,space_id) REFERENCES concepts(id,space_id));
CREATE TABLE IF NOT EXISTS memories (
 id text PRIMARY KEY, owner_id text NOT NULL, source_space_id text NOT NULL REFERENCES spaces(id), concept_id text,
 kind text NOT NULL, content text NOT NULL, valid boolean NOT NULL DEFAULT true, source_id text NOT NULL,
 created_at timestamptz DEFAULT now(), superseded_by text,
 FOREIGN KEY(concept_id,source_space_id) REFERENCES concepts(id,space_id));
CREATE TABLE IF NOT EXISTS chats (
 id text PRIMARY KEY, space_id text NOT NULL REFERENCES spaces(id), owner_id text NOT NULL,
 history jsonb NOT NULL DEFAULT '[]', corrections jsonb NOT NULL DEFAULT '[]', created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS events (
 id bigserial PRIMARY KEY, space_id text REFERENCES spaces(id), session_id text REFERENCES sessions(id),
 kind text NOT NULL, payload jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS model_calls (
 id bigserial PRIMARY KEY, payload jsonb NOT NULL, created_at timestamptz DEFAULT now());
CREATE TABLE IF NOT EXISTS schema_versions (version integer PRIMARY KEY, applied_at timestamptz DEFAULT now());
INSERT INTO schema_versions(version) VALUES (1) ON CONFLICT DO NOTHING;
