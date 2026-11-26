# AI OFFICE (봇오피스)

나(CEO)와 AI 직원 4명이 **프로젝트 방**에서 함께 일하는 개인용 AI 업무 시스템.

- **주소**: https://mungcare-lab.github.io/bot-office/
- **데이터베이스**: Supabase (Free) · 프로젝트 `ai-office` · 리전 서울(ap-northeast-2)
- **로그인**: 이메일 + 비밀번호 / 이메일 로그인 링크(매직 링크)

## 지금 되는 것 (V1.0 · 1~3단계)
- **계정 인증** — Supabase Auth 이메일 로그인·가입. 세션은 브라우저에 유지된다.
- **프로젝트 방 6개 자동 생성** — AI OFFICE 본사 · Replay Me · 사운드오브클래식 · CROWN OF ASH · PAW PICK · 신규 사업 개발
- **AI 직원 5명 자동 배치** — CEO(나) · ChatGPT · Claude · Pickle · Gemini (방마다 최대 10명까지 확장 가능)
- **실시간 저장** — 메시지는 Supabase Postgres에 저장되고 새로고침·다른 기기에서도 그대로 보인다(postgres_changes 구독).
- **@멘션 · @전체 호출** — 입력창에서 `@`를 누르면 AI 선택 목록이 뜬다.
- **업무 요청 모드** — 📋 버튼으로 업무 요청(task)으로 보낼 수 있고 진행 상태(요청됨/진행 중/검수 대기/완료/보류)를 표시한다.
- **파일·이미지 첨부** — 비공개 Storage 버킷(`office-files`)에 올리고 서명 URL로 본다.
- **모바일 UI / 다크 모드 / PWA** — 390px 기준 카카오톡 스타일, 홈 화면 추가 지원(`manifest.webmanifest`, `sw.js`).
- **고전 봇오피스 유지** — 주소 뒤에 `#local`(또는 기존 `?room=` 초대 링크)로 열면 이전 로컬/P2P 채팅 화면이 그대로 동작한다.

## 아직 안 되는 것 (의도적으로 비워 둔 부분)
- **AI의 실제 답변** — ChatGPT·Claude·Pickle·Gemini는 아직 API가 연결되지 않았다. 호출하면 “API 미연결(수동 대기)”로만 표시하고, **AI가 답한 것처럼 꾸민 메시지는 만들지 않는다.** (DB RLS가 `author_kind='ai'` 메시지의 클라이언트 생성을 차단한다.)
- 공유 기억 시스템(4단계), Gemini 무료 API 연동(5단계), ChatGPT·Claude 선택 연동(6단계), 자동 업무 분배·검수(7단계).
- 대화 내보내기, 채팅 내역 검색.

## 보안
- 프런트엔드에는 **공개용 anon 키만** 들어간다. 이 키는 공개되어도 되며, 실제 데이터 접근은 전부 **RLS 정책**이 막는다.
- `service_role` 키, AI 제공자 API 키, DB 비밀번호는 저장소에 없다. AI 키는 5~6단계에서 **서버 측 함수(Edge Function)의 비밀값**으로만 넣는다.
- 테이블: `profiles` · `projects` · `project_members` · `ai_agents` · `messages` · `project_memories` · `api_usage_logs` (모두 RLS 적용, 스키마는 `src/office/schema.sql`)

## 업데이트
소스는 코코 작업 공간의 `work/bot-office/`. `npm run build` 후 `dist/`를 이 저장소 루트로 올리면 반영된다.
