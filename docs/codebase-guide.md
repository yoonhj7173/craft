# 코드베이스 가이드 (비개발 PM용)

> 이 문서는 코드를 직접 짜지 않는 PM이 이 제품을 **혼자 유지보수**할 수 있도록 만든 지도입니다.
> Java/Spring 부트캠프 수준의 기초만 있어도 따라올 수 있게, 곳곳에 **Spring 비유**를 달았습니다.

---

## 0. 30초 요약

- **제품 한 줄**: pondas.ai — AI 에이전트들이 "사무실 맵" 안에서 팀(방)을 이루고, 사용자가 채팅 한 줄로 회사 전체를 지휘하면 에이전트들이 일을 주고받으며 결과물(문서·코드)을 만들어내는 서비스.
- **기술 스택**:
  1. **백엔드** = Python **FastAPI**(= Spring Boot) + **SQLAlchemy**(= JPA) + **Celery**(= 비동기 작업 큐) + **Redis**(실시간 알림 통로) + **PostgreSQL**(DB).
  2. **프론트엔드** = **Next.js 14**(React) + **Zustand**(화면 상태 보관소) + **Pixi.js**(사무실 맵 그리는 캔버스) + **SSE**(서버가 실시간으로 화면에 상태를 밀어줌).
  3. **AI 실행** = LiteLLM/CrewAI(글쓰기형 팀) + E2B 샌드박스/CMA(코딩형 팀). 인증 = **Clerk**(= Spring Security).
- **가장 중요한 파일 1개**: [orchestrator.py](../backend/app/services/orchestrator.py) 의 `run_chat` 함수. 사용자의 채팅 한 줄을 받아 "누구에게 무슨 일을 시킬지"를 AI가 스스로 판단해 실행하는 **제품의 심장**입니다.
- **핵심 동작 구조**: 사용자가 채팅으로 지시 → 지휘자(orchestrator)가 작업을 만들어 에이전트에게 던짐 → 백그라운드 일꾼이 LLM을 돌려 처리 → 끝나면 **연결선(엣지)**을 따라 다음 에이전트에게 자동으로 일이 넘어감(자동 전파) → 모든 변화가 실시간(SSE)으로 사무실 맵에 표시됨.
- **수익 구조(메모 참고)**: 크레딧 + 프리미엄 모델. LLM 토큰 사용량을 작업마다 계산해 저장하고(비용 추적), 하루 비용 한도/동시 실행 한도 같은 안전장치(가드레일)로 비용 폭주를 막습니다.

---

## 0.5 이 가이드 사용법 (지도 ↔ 표지판)

이 문서와 코드 주석은 **짝**으로 쓰도록 만들었습니다.

- **가이드(이 문서) = 지도**: 어디서부터 볼지, 큰 그림이 어떻게 생겼는지 알려줍니다.
- **코드 주석 = 길 위의 표지판**: 각 함수 위에 한국어 설명 블록이 있고, 그 안의 `누가 부르나` / `연결` 줄이 **"다음에 열어볼 파일"**을 가리킵니다.

**추천 사용 흐름**:
1. 이 가이드 **3장(읽기 순서)**에서 지금 볼 파일을 정합니다.
2. 그 파일을 열어 함수 위 주석을 읽습니다.
3. 주석의 `연결:` 줄이 가리키는 파일로 이동합니다. (예: "연결: process_task → worker_core.py")
4. 그렇게 표지판을 따라가면 자연스럽게 한 흐름이 머릿속에 그려집니다.

코드 주석 형식은 이렇게 생겼습니다:

```
"""함수이름 — 한 줄 요약.

무슨 일을 하나: ...
누가 부르나: ...   (어디서 이걸 호출하는지)
처리 순서: ...      (안에서 차례로 일어나는 일)
연결: ...           (관련 다른 파일 = 다음에 볼 곳)
"""
```

---

## 1. 폴더 / 파일 구조

최상위에서 **실제 제품 코드는 딱 두 폴더**입니다: `backend/`(두뇌)와 `frontend/`(화면). 나머지는 문서나 빌드 도구입니다.

- [backend/](../backend/) — Python 백엔드 (= Spring Boot 프로젝트 전체)
  - [backend/app/main.py](../backend/app/main.py) — 앱 조립 지점. 모든 라우터가 여기 붙는다 (= `@SpringBootApplication` + 디스패처).
  - [backend/app/models.py](../backend/app/models.py) — DB 테이블 정의 (= JPA `@Entity` 모음). **데이터 모양을 알면 절반은 이해한 것.**
  - [backend/app/schemas.py](../backend/app/schemas.py) — 요청/응답 객체 (= DTO).
  - [backend/app/routers/](../backend/app/routers/) — API 입구들 (= `@RestController` 모음). 종류별로 파일 분리.
  - [backend/app/services/](../backend/app/services/) — 비즈니스 로직 (= `@Service` 모음). **진짜 일이 일어나는 곳.**
  - [backend/app/auth.py](../backend/app/auth.py) — 로그인 검증 + 데이터 격리 (= Spring Security).
  - [backend/app/db.py](../backend/app/db.py) — DB 연결/세션 (= EntityManager 설정).
  - [backend/app/config.py](../backend/app/config.py) — 환경설정 (= `application.yml`).
  - [backend/app/catalog.py](../backend/app/catalog.py) — 팀/역할 마스터 데이터(시드).
  - [backend/app/celery_app.py](../backend/app/celery_app.py) — 비동기 작업 큐 설정 (= `@Async` 인프라).
- [frontend/](../frontend/) — Next.js 프론트엔드 (= 화면 전체)
  - [frontend/app/](../frontend/app/) — 페이지들(파일 경로 = URL 경로). 랜딩/온보딩/메인맵 등.
  - [frontend/components/](../frontend/components/) — 화면 조각(맵·HUD·패널·모달·오버레이).
  - [frontend/lib/](../frontend/lib/) — 공용 로직: [api.ts](../frontend/lib/api.ts)(백엔드 호출), [store.ts](../frontend/lib/store.ts)(상태 보관소), [sse.ts](../frontend/lib/sse.ts)(실시간 연결).
- 그 외 (지금은 신경 안 써도 됨):
  - [specs/](../specs/) — 기획/설계 문서(PRD·기술설계). 코드 아님.
  - `.claude/`, `runs/`, `context/`, `craft` — 이 제품을 *만드는 데 쓴* AI 작업 도구. 제품 코드 아님.

---

## 2. 데이터 흐름

### 2-1. 레이어 큰 그림

Spring의 Controller → Service → Repository(Entity) 3층과 거의 같습니다.

```
[브라우저 / 프론트엔드]
   frontend/lib/api.ts  (모든 API 호출의 공통 창구)
        |
        v   HTTP 요청 (+ 로그인 토큰)
   ┌─────────────────────────────────────────────┐
   │ 백엔드 (FastAPI)                              │
   │                                              │
   │  routers/*.py    (@RestController = API 입구) │
   │        |                                     │
   │        v                                     │
   │  services/*.py   (@Service = 비즈니스 로직)    │
   │        |                                     │
   │        v                                     │
   │  models.py       (@Entity = DB 테이블)        │
   └─────────────────────────────────────────────┘
        |
        v   PostgreSQL (진짜 데이터 = '권위')
```

여기에 두 가지가 더 얹힙니다:
- **백그라운드 일꾼(Celery 워커)**: 오래 걸리는 AI 작업은 API가 직접 안 하고 **큐에 던진 뒤** 워커가 따로 처리합니다. (사용자를 기다리게 하지 않으려고)
- **실시간 통로(SSE + Redis)**: 작업 상태가 바뀌면 서버가 브라우저로 이벤트를 밀어, 새로고침 없이 맵이 살아 움직입니다.

### 2-2. 핵심 기능 1개의 전체 흐름: "채팅으로 일 시키기"

사용자가 채팅창에 *"리서치팀에 경쟁사 조사 시켜줘"*라고 쳤을 때:

```
1. [프론트] 채팅 입력
   frontend/components/hud/Hud.tsx (OrchestratorChat)
        | onSend
        v
   frontend/app/app/[projectId]/page.tsx (sendChat)
        | apiFetch → POST /api/projects/{id}/chat
        v
2. [백엔드 입구]
   backend/app/routers/chat.py (chat)
        | 로그인·소유권 확인 후 run_chat 호출
        v
3. [지휘자 두뇌 = 심장]
   backend/app/services/orchestrator.py (run_chat)
        | LLM이 '툴루프'를 돌며 도구를 고름
        |   - create_goal  (목표 만들기)
        |   - dispatch_task (에이전트에게 작업 던지기) → 큐에 등록(enqueue)
        v
4. [큐 → 백그라운드 일꾼]
   backend/app/celery_app.py (enqueue_task → run_task)
        v
5. [작업 처리 엔진]
   backend/app/services/worker_core.py (process_task)
        | try_dispatch (5게이트 통과 확인, task_service.py)
        | assemble_prompt (프롬프트 조립, prompt.py)
        | LLM 실행 → 결과 분류 (done / needs-input / failed)
        v
6. [완료 후 자동 전파]
   backend/app/services/graph_engine.py (propagate)
        | 연결선(엣지)을 따라 다음 에이전트의 작업을 자동 생성 → 다시 4번 큐로
        v
7. [실시간 반영]
   backend/app/services/events.py (emit_status/emit_terminal_notification)
        | Redis 채널로 이벤트 발행
        v
   backend/app/routers/realtime.py (sse)  →  frontend/lib/sse.ts (connectSSE)
        | store.applyStatus 등 호출
        v
   frontend/lib/store.ts → 맵 캐릭터·알림벨이 실시간 갱신
```

**핵심 통찰**: 사용자는 **단 하나의 채팅창**으로만 지휘하고, 그 뒤의 작업 생성·실행·전파·표시는 전부 자동입니다. 그래서 `run_chat`(3번)과 `process_task`(5번)와 `propagate`(6번) 이 셋만 이해하면 제품의 80%를 이해한 것입니다.

### 2-3. 비동기 실행: API와 워커는 왜 나뉘어 있나 (가장 헷갈리는 부분)

**왜 나눴나**: LLM 호출이 너무 느립니다(리서치 30초, 코딩 몇 분). API가 그걸 직접 다 하고 나서 응답하면 브라우저는 몇 분간 멈춘 화면을 보다 타임아웃됩니다. 그래서 **"주문 접수"(API)와 "요리"(워커)를 분리**했습니다.

물리적으로 **서로 다른 프로세스 2개가 동시에** 떠 있습니다:

- `uvicorn app.main:app` — **API 서버**. HTTP 요청을 받음. 빠르게 응답해야 함.
- `celery -A app.celery_app worker` — **워커**. 큐에서 일을 꺼내 LLM을 실제 실행. 느려도 됨.

둘은 직접 대화하지 않고 **Redis(큐)를 통해서만** 일을 주고받습니다.

```
[브라우저] ──HTTP──> [API 프로세스]  ──★task 번호표를 큐에 넣음──> [Redis 큐]
                         │                                          │
                  즉시 응답(지휘자 답 말풍선)                         │ 워커가 꺼냄
                         ▼                                          ▼
                  유저는 "접수됨"을 봄                        [워커 프로세스]
                                                              LLM 실제 실행(느림)
                                                                   │
                  맵 캐릭터 실시간 갱신 <──SSE/Redis── emit_status ◀┘
```

**식당 비유**: API = 웨이터(주문 받아 주방에 표 꽂고 "주문 들어갔습니다" 하고 바로 다음 손님으로). 워커 = 요리사(꽂힌 표를 가져가 실제로 요리). 큐(Redis) = 주문표 꽂이대.

**"즉시 응답"의 정체**: API가 돌려주는 `{reply, actions}`는 *작업 결과물*이 아니라 *지휘자의 접수 확인 메시지*("Researcher에게 맡겼어요")입니다. 진짜 결과물은 한참 뒤 워커가 끝낸 뒤 **실시간 신호(SSE)로 별도 통로로** 도착합니다. 즉 **채팅 응답과 작업 결과는 다른 시점·다른 통로**로 옵니다.

**디스패치 = "작업을 일꾼에게 넘겨 실행을 개시시키는 것"**, 두 단계로 일어납니다:
- 1단계 *작업 투입* — `dispatch_task` ([orchestrator.py](../backend/app/services/orchestrator.py)): task를 만들어 큐에 넣음(주문표 꽂기).
- 2단계 *실행 개시* — `try_dispatch` ([task_service.py](../backend/app/services/task_service.py)): 큐에서 꺼낸 task를 5게이트에 통과시켜 `queued`→`working`으로 출발(불 켜기).

**5게이트(`dispatch_blockers`)** — 작업을 출발시키기 전 통과해야 하는 비용·과부하 안전장치. 하나라도 걸리면 `queued`에 머뭅니다:
1. `project_paused` — 프로젝트 일시정지면 차단.
2. `agent_busy` — 그 에이전트가 이미 일하는 중이면 차단(한 명당 한 번에 1건).
3. `concurrency_cap` — 사용자가 동시에 돌리는 작업 수 한도(기본 3) 초과 시 차단.
4. `daily_cost_cap` — 오늘 LLM 비용이 하루 한도(기본 $10) 초과 시 차단.
5. `goal_chain_budget` — 한 목표의 작업이 너무 불어나면(기본 25) 차단.

**병렬성 오해 주의**: 큐를 쓰는 이유는 "하나씩 돌려서"가 아니라 ①느린 작업이 HTTP를 막지 않게 ②5게이트로 *통제된 병렬*(적당히 동시에, 한도 안에서)을 위해서입니다. 작업은 여러 개가 동시에 돌 수 있습니다.

**상태 흐름 요약**: 작업은 항상 `queued`(대기열)에서 시작 → 게이트 통과하면 `working` → `done`/`failed`/`needs-input`/`blocked`. (`idle`은 DB에 저장 안 되는, "진행 중 작업 없음"의 화면 표시값일 뿐입니다.)

---

## 3. 리뷰(읽기) 순서

이 순서대로 따라가면 길을 잃지 않습니다. **코드보다 "무엇을 만들었는지" 문서를 먼저** 보는 게 핵심입니다.

1. **무엇을/왜 만드는지 (코드 아님)**
   - [specs/prd.md](../specs/prd.md) — 제품이 뭐고 왜 만드는지.
   - [specs/user-flows.md](../specs/user-flows.md) — 사용자가 어떤 흐름으로 쓰는지.
   - [specs/tech-design.md](../specs/tech-design.md) — 기술 구조 전체 지도(필요할 때 참고용).
2. **데이터 모양 (절반의 이해)**
   - [backend/app/models.py](../backend/app/models.py) — DB 테이블들. projects → teams → agents → tasks 의 부모-자식 관계와 7가지 작업 상태를 눈에 익히세요.
3. **심장 (요청→처리→응답)** ← 가장 중요
   - [backend/app/main.py](../backend/app/main.py) — 모든 게 어떻게 조립되는지.
   - [backend/app/routers/chat.py](../backend/app/routers/chat.py) — 채팅 입구.
   - [backend/app/services/orchestrator.py](../backend/app/services/orchestrator.py) — 지휘자 두뇌(`run_chat`).
   - [backend/app/services/worker_core.py](../backend/app/services/worker_core.py) — 작업 처리 엔진(`process_task`).
   - [backend/app/services/task_service.py](../backend/app/services/task_service.py) — 상태 전이 + 5게이트.
   - [backend/app/services/graph_engine.py](../backend/app/services/graph_engine.py) — 자동 전파(`propagate`).
   - [backend/app/services/prompt.py](../backend/app/services/prompt.py) — 프롬프트 조립.
4. **주변 기능 (필요할 때 골라 읽기)**
   - 인증/격리: [auth.py](../backend/app/auth.py), [ownership.py](../backend/app/ownership.py)
   - CRUD: [projects.py](../backend/app/routers/projects.py), [teams.py](../backend/app/routers/teams.py), [edges.py](../backend/app/routers/edges.py)
   - 실시간/결과물: [realtime.py](../backend/app/routers/realtime.py), [events.py](../backend/app/services/events.py), [outputs.py](../backend/app/routers/outputs.py)
   - 코딩 에이전트: [dev_runner.py](../backend/app/services/dev_runner.py), [sandbox.py](../backend/app/services/sandbox.py), [cma_engine.py](../backend/app/services/cma_engine.py)
5. **프론트엔드 (백엔드 이해 후)**
   - [frontend/lib/api.ts](../frontend/lib/api.ts) → [frontend/lib/store.ts](../frontend/lib/store.ts) → [frontend/lib/sse.ts](../frontend/lib/sse.ts)
   - [frontend/app/app/%5BprojectId%5D/page.tsx](../frontend/app/app/%5BprojectId%5D/page.tsx) — 메인 화면 \[projectId\] (백엔드를 잇는 허브)
   - [frontend/components/hud/Hud.tsx](../frontend/components/hud/Hud.tsx), [frontend/components/panels/PanelController.tsx](../frontend/components/panels/PanelController.tsx)

---

## 4. 기능별 핵심 함수

> 모든 함수가 아니라 **흐름상 중요한 것만** 골랐습니다. 각 함수에는 코드에도 같은 이름의 한국어 주석이 달려 있어, 이 표에서 본 함수를 코드에서 그대로 찾을 수 있습니다.
> (새 기능이 생기면 아래에 한 줄씩 추가해 확장하세요.)

### 채팅 → 지휘 (심장)
- `chat` ([chat.py](../backend/app/routers/chat.py)) — 채팅 보내기 입구. 로그인·소유권 확인 후 지휘자 호출.
- `run_chat` ([orchestrator.py](../backend/app/services/orchestrator.py)) — **제품의 심장.** 사용자 한 마디로 LLM 툴루프를 돌려 실제 작업을 시킨다.
- `_tool_dispatch_task` ([orchestrator.py](../backend/app/services/orchestrator.py)) — 지휘자가 에이전트에게 작업을 던지는 도구.
- `_tool_resume_task` ([orchestrator.py](../backend/app/services/orchestrator.py)) — 질문하며 멈춘 에이전트에게 답을 주고 재개하는 도구.

### 작업 처리 (백그라운드 일꾼)
- `enqueue_task` / `run_task` ([celery_app.py](../backend/app/celery_app.py)) — 작업을 큐에 넣고, 워커가 꺼내 실행.
- `process_task` ([worker_core.py](../backend/app/services/worker_core.py)) — **작업 1건을 실제로 실행하는 일꾼.** 엔진 분기(글쓰기형/코딩형).
- `create_task` ([task_service.py](../backend/app/services/task_service.py)) — 새 작업을 '대기' 상태로 생성.
- `try_dispatch` / `dispatch_blockers` ([task_service.py](../backend/app/services/task_service.py)) — 시작해도 되는지 5게이트(비용/동시성 등) 검사 후 출발.
- `transition` ([task_service.py](../backend/app/services/task_service.py)) — 모든 상태 변경이 거치는 단 하나의 검문소.
- `assemble_prompt` ([prompt.py](../backend/app/services/prompt.py)) — LLM에 보낼 지시문 한 통을 여러 재료로 조립.

### 자동 전파 (이어달리기)
- `propagate` ([graph_engine.py](../backend/app/services/graph_engine.py)) — **작업 완료 시 연결선을 따라 다음 에이전트 작업을 자동 생성.**
- `_on_reviewer_done` ([graph_engine.py](../backend/app/services/graph_engine.py)) — 검토 반복(review loop)에서 통과/수정요청 분기.
- `validate_and_build_edge` ([edge_ops.py](../backend/app/edge_ops.py)) — 연결선 생성 시 규칙(출력 1개·사이클 금지 등) 검증.

### 인증 / 데이터 격리 (= Spring Security)
- `require_user` ([auth.py](../backend/app/auth.py)) — 로그인 검문. 토큰 검증 후 '누구인지' 반환.
- `TenantScope` ([auth.py](../backend/app/auth.py)) — 모든 조회를 '로그인한 그 사람 것'으로 자동으로 좁힘.
- `load_owned_project` ([ownership.py](../backend/app/ownership.py)) — 내 프로젝트가 아니면 못 찾은 척(404).

### 프로젝트 / 팀 / 에이전트
- `create_project` ([projects.py](../backend/app/routers/projects.py)) — 새 사무실 + 고른 팀들 + 시작 멤버를 한 번에 생성.
- `_build_map` ([projects.py](../backend/app/routers/projects.py)) — 사무실 맵을 그릴 모든 데이터를 한 덩어리로.
- `add_agent` ([teams.py](../backend/app/routers/teams.py)) — 팀에 직원 추가(5명 제한 + 출력 연결).
- `create_edge` ([edges.py](../backend/app/routers/edges.py)) — 맵에서 그은 연결선을 저장.

### 실시간 / 결과물 / 사용량
- `sse` ([realtime.py](../backend/app/routers/realtime.py)) — 서버→브라우저 실시간 통로.
- `emit_status` / `emit_terminal_notification` ([events.py](../backend/app/services/events.py)) — 상태 변화·완료 알림을 실시간 발행.
- `board` / `usage` ([realtime.py](../backend/app/routers/realtime.py)) — 작업 보드, 토큰/비용 집계.
- `list_outputs` ([outputs.py](../backend/app/routers/outputs.py)) — 에이전트들이 만든 결과 파일 목록.
- `cost_usd` / `load_config` ([config_store.py](../backend/app/services/config_store.py)) — 비용 계산, 운영 한도값 읽기.

### 코딩 에이전트 (개발/디자인팀)
- `run_dev_task` ([dev_runner.py](../backend/app/services/dev_runner.py)) — 샌드박스에서 AI가 코드를 쓰고·돌려보고·고치는 루프.
- `get_provider` ([sandbox.py](../backend/app/services/sandbox.py)) — **보안 핵심:** AI 코드를 어디서 돌릴지(E2B 격리 vs 금지) 결정.
- `ensure_running` / `pause_if_idle` ([workspace.py](../backend/app/services/workspace.py)) — 샌드박스 켜기/재우기(비용 절약).
- `collect_outputs` ([verification.py](../backend/app/services/verification.py)) — 샌드박스가 만든 파일을 결과물로 수집.
- `run_dev_task_cma` ([cma_engine.py](../backend/app/services/cma_engine.py)) — 코딩 작업을 Claude 관리형 에이전트(CMA)에 위임하는 대안 경로.

### 프론트엔드
- `apiFetch` ([api.ts](../frontend/lib/api.ts)) — 프론트의 모든 백엔드 호출 공통 창구.
- `useStore` ([store.ts](../frontend/lib/store.ts)) — 화면 전체가 공유하는 상태 보관소.
- `connectSSE` ([sse.ts](../frontend/lib/sse.ts)) — 실시간 이벤트를 받아 store에 반영.
- `ProjectMap` ([page.tsx](../frontend/app/app/%5BprojectId%5D/page.tsx)) — 메인 화면 허브(맵+HUD+패널 조립).
- `Hud` / `OrchestratorChat` ([Hud.tsx](../frontend/components/hud/Hud.tsx)) — 맵 위 조작 레이어 + 지휘 채팅창.
- `PanelController` ([PanelController.tsx](../frontend/components/panels/PanelController.tsx)) — 선택에 따라 패널/모달을 띄우고 동작 처리.
- `MapCanvas` ([MapCanvas.tsx](../frontend/components/map/MapCanvas.tsx)) — Pixi.js로 사무실 맵을 그리는 화면.

---

## 5. 파인튜닝 가이드 — "이걸 바꾸고 싶다 → 어디를 보나"

> 제품을 손볼 때 가장 자주 건드릴 지점들을 모았습니다. 먼저 알아둘 큰 원칙 하나:

**설정값은 두 군데에 삽니다.**
- **코드 기본값(시드)**: 앱을 처음 깔 때 DB에 심어지는 출발값. 영구히 기본을 바꾸려면 여기를 고치고 재배포/재시드.
- **라이브 config 테이블(DB)**: 운영 중 **재배포 없이** 바꿀 수 있는 값. 급히 한도만 조절할 땐 이 테이블의 행을 수정.
- 읽는 통로는 항상 [config_store.py](../backend/app/services/config_store.py)의 `load_config` 하나입니다. (코드는 이걸 통해서만 값을 읽음)

### 5-1. 에이전트의 "성격/실력" 관련

- **에이전트의 역할·지시문(말투·일하는 방식)을 바꾸고 싶다**
  → [catalog.py](../backend/app/catalog.py)의 역할 프롬프트들(`_PM`, `_SWE`, `_QA` …). 원본 출처는 [specs/role-catalog.md](../specs/role-catalog.md).
  → (특정 프로젝트의 한 에이전트만 즉석에서 바꾸려면 UI의 에이전트 편집 → `update_agent` in [teams.py](../backend/app/routers/teams.py), `agent.role_instructions`.)
- **어떤 팀/역할이 존재하는지(카탈로그 자체)를 바꾸고 싶다**
  → [catalog.py](../backend/app/catalog.py)의 `TEAM_TEMPLATES`. 팀 추가/삭제, 역할 추가가 여기.
- **팀의 기본 협업 배선(누가 누구에게 자동으로 넘기는지)을 바꾸고 싶다**
  → [catalog.py](../backend/app/catalog.py)의 `TEAM_TEMPLATES` 안 `default_output_*` 값(예: architect→swe handoff, qa→swe review_loop).
- **등급(strong/medium/light)이 실제로 어떤 모델을 쓰는지 바꾸고 싶다**
  → 기본값: [catalog.py](../backend/app/catalog.py)의 `TIER_MODELS`. 읽기: [config_store.py](../backend/app/services/config_store.py)의 `model_for_tier`. 라이브: config 테이블 `tier_models`.

### 5-2. 비용·한도(가드레일) 관련

- **모델 토큰 단가(비용 계산)를 바꾸고 싶다**
  → 기본값: [catalog.py](../backend/app/catalog.py)의 `MODEL_PRICING`. 계산: [config_store.py](../backend/app/services/config_store.py)의 `cost_usd`. 라이브: config 테이블 `model_pricing`.
- **하루 비용 한도·동시 실행 한도를 바꾸고 싶다**
  → 기본값: [config.py](../backend/app/config.py)(`daily_cost_cap_usd`, `concurrency_cap`) + [catalog.py](../backend/app/catalog.py)의 `config_seed`. 검사 로직: [task_service.py](../backend/app/services/task_service.py)의 `dispatch_blockers`(5게이트). 라이브: config 테이블. (운영 중엔 설정 화면에서도 조절 — [Overlays.tsx](../frontend/components/overlays/Overlays.tsx)의 `SettingsOverlay`)
- **한 목표가 작업을 몇 개까지 불릴 수 있는지(증식 한도)를 바꾸고 싶다**
  → config 테이블 `goal_chain_budget`(기본 25). 시드는 [catalog.py](../backend/app/catalog.py)의 `config_seed`.

### 5-3. 동작·실행 관련

- **지휘자(오케스트레이터)의 행동 규칙이나 쓸 수 있는 도구를 바꾸고 싶다**
  → [orchestrator.py](../backend/app/services/orchestrator.py)의 `_system_prompt`(지휘자 지침) + `TOOL_SCHEMAS`(도구 목록).
- **에이전트 프롬프트에 무엇이 어떤 순서로 들어가는지 바꾸고 싶다**
  → [prompt.py](../backend/app/services/prompt.py)의 `assemble_prompt`(역할→컨텍스트→기억→입력→지시→규약 순). 질문 센티넬 문구는 같은 파일 `_PROTOCOL`.
- **컨텍스트 주입 토큰 예산을 바꾸고 싶다**
  → config 테이블 `context_token_budget`(기본 100000). 적용: [prompt.py](../backend/app/services/prompt.py).
- **개발팀 실행 엔진(CMA vs E2B 샌드박스)을 바꾸고 싶다**
  → config 테이블 `dev_engine`(`cma`/`e2b`). 분기: [worker_core.py](../backend/app/services/worker_core.py)의 `process_task`. 기본값: [config_store.py](../backend/app/services/config_store.py)의 `_DEFAULTS`.
- **코딩 작업 타임아웃·최대 스텝을 바꾸고 싶다**
  → [dev_runner.py](../backend/app/services/dev_runner.py)의 `MAX_STEPS`, `PER_COMMAND_TIMEOUT_SEC` + config 테이블 `dev_task_timeout_min`.
- **검토 반복(review loop) 최대 횟수를 바꾸고 싶다**
  → 연결선별 값(`max_iterations`)이라 UI에서 설정. 규칙·범위 검증: [edge_ops.py](../backend/app/edge_ops.py). 사용: [graph_engine.py](../backend/app/services/graph_engine.py).
- **업로드 가능한 파일 종류를 바꾸고 싶다**
  → [extract.py](../backend/app/services/extract.py)의 허용 확장자(`TEXT_EXTS`/`PDF_EXTS`).

### 5-4. 화면(프론트) 관련

- **상태별 색·표정·라벨(맵 캐릭터 비주얼)을 바꾸고 싶다**
  → [frontend/lib/tokens.ts](../frontend/lib/tokens.ts)(상태→색/칩 매핑).
- **랜딩/마케팅 문구를 바꾸고 싶다**
  → [frontend/app/page.tsx](../frontend/app/page.tsx).
- **온보딩 단계·문구를 바꾸고 싶다**
  → [frontend/app/onboarding/page.tsx](../frontend/app/onboarding/page.tsx).
