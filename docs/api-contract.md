# Local demo API contract (v1)
All routes /api, JSON errors {detail: Chinese text}, single local user. Server validates every object scope. No frontend grading. UUID strings. GET health {provider,model,ready,database,embedding,...}. JSON bodies unless upload.

- GET /spaces -> array {id,name,kind:course|focus,topic,created_at}
- POST /spaces {name,kind,topic} -> space
- GET /spaces/{space}/overview -> {space,documents:[{id,filename,status,reason,source_url}],concepts:[{id,name,description,evidence_ids,mastery:{score:null|float,attempts,streak,errors}}],graph:{nodes,edges},sessions:[{id,status,goal_concept_id,current_concept_id,thread_id}],memories:[...]}
- POST /spaces/{space}/documents multipart file + optional source_url -> document {id,status,reason}; PDF/TXT/MD; upload synchronous loading
- GET /spaces/{space}/documents/{doc}/file -> actual PDF/text
- POST /spaces/{course}/admit {source_space_id,document_id} -> document, revalidate under target; independent mastery
- POST /chat {space_id:optional,chat_id:optional,message,baseline:false} -> {chat_id,answer,citations:[{evidence_id,document_id,page,section,text,quote,filename,url}],decision:{action,space_id,concept_id,evidence_ids,reason},gap,provider}. Null scope -> clarify.
- POST /spaces/{space}/sessions {concept_id} -> public session view
- GET /spaces/{space}/sessions/{session} -> public session view
- POST /spaces/{space}/sessions/{session}/answer {quiz_id,submission_id,answer} -> public session view
- POST /spaces/{space}/sessions/{session}/resume {} -> public session view
- POST /spaces/{space}/sessions/{session}/stop {} -> public session view
- POST /spaces/{space}/preferences {content} -> memory validation response
- GET /spaces/{space}/traces?session_id=... -> array {id,kind,payload,created_at}; concise reasons/tools results only

Public session view: {id,space_id,thread_id,status:waiting|running|paused|stopped|completed|error|needs_clarification,goal_concept_id,current_concept_id,step,explanation,mode:explanation|example|quiz,feedback:null|{correct,score,feedback},quiz:null|{id,question,options:[string],concept_id,evidence_ids},citations:[],decision:{action,...},error:null|str}. Never correct_index/rubric/answer_explanation before submission. Refresh GET returns persisted current quiz and explanation. Pause is leaving a waiting quiz; resume recovers failed graph or paused quiz.
