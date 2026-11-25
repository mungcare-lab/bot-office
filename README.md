# 봇오피스 (Bot Office)

사람과 여러 AI가 한 방에서 같이 일하는 단체 채팅방.

- **주소**: https://mungcare-lab.github.io/bot-office/
- **초대**: 방에서 `사람 초대` → 링크 복사. 링크를 받은 사람은 같은 방에 합류합니다.
- **AI 팀**: 기본 3명(제미나이·챗GPT·기획자), 최대 10명까지 추가·편집.
- **멘션**: 입력창에서 `@`로 AI를 부르면 여러 AI가 병렬로 답합니다. `@전체`는 방의 모든 AI.
- **API 키**: 설정에서 Google Gemini / OpenAI 키를 넣으면 실제 AI가 답합니다. 키는 브라우저(localStorage)에만 저장되고 해당 서비스로만 전송됩니다. 봇오피스 자체 서버는 없습니다.
- **동기화**:
  - 같은 브라우저 탭끼리: BroadcastChannel로 즉시 동기화.
  - 다른 기기: PeerJS(WebRTC) P2P — 방장이 앱을 열어 두면 초대 링크로 합류.
  - 방장이 오프라인일 때도 이어가려면 설정에서 Supabase(URL + Anon Key, SQL 1회 실행)를 연결.
- **저장**: 방마다 멤버·AI·대화 기록이 브라우저 localStorage에 독립 저장됩니다.

## 개발

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # dist/
node qa/run.mjs  # Playwright QA + 스크린샷 (qa/)
```

Vite + React + TypeScript. 빌드 산출물은 상대 경로(`base: './'`)라 GitHub Pages 하위 경로에서 그대로 동작합니다.
