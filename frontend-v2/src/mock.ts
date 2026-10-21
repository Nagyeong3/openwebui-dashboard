import type { Snapshot, User, Usage } from "./domain";
import { addDays } from "./domain";
// Entirely fictional demo fixtures. No actual employee or organization data.
export function createMock(): Snapshot {
  const teams = [
    "플랫폼팀",
    "서비스팀",
    "데이터팀",
    "연구개발팀",
    "사업기획팀",
    "기술지원팀",
  ];
  const users: User[] = Array.from({ length: 120 }, (_, i) => ({
    id: `demo-db-${String(i + 1).padStart(3, "0")}`,
    name: `데모 사용자 ${String(i + 1).padStart(3, "0")}`,
    division: i % 6 < 3 ? "기술본부" : "서비스본부",
    team: teams[i % 6],
    position: i < 18 ? "팀장" : i % 4 === 0 ? "책임" : "연구원",
    mapping: i === 119 ? "중복 이름" : i > 116 ? "미매핑" : "매핑 완료",
    source: "openwebui-db",
  }));
  const usage: Usage[] = [];
  const categories = [
    "문서·RAG",
    "코드·개발",
    "정보 검색",
    "요약·정리",
    "업무 작성",
    "번역",
  ];
  for (let d = 0; d < 84; d++) {
    const date = addDays("2026-07-30", d);
    for (let i = 0; i < 120; i++) {
      if ((i >= 14 && i < 18) || i % 9 === 8 || i >= 112 || (i + d) % 5 === 0)
        continue;
      const weekday = new Date(date + "T00:00:00Z").getUTCDay();
      const questions = Math.max(
        0,
        Math.round(
          (2 + ((i * 7 + d * 3) % 13)) *
            (weekday === 0 || weekday === 6 ? 0.22 : 1) *
            (d < 54 ? 0.78 : 1.12),
        ),
      );
      if (!questions) continue;
      const prompt = questions * (940 + ((i * 193 + d * 97) % 2100));
      const completion = questions * (100 + ((i * 17 + d * 7) % 420));
      usage.push({
        date,
        userId: users[i].id,
        model: ["gpt-oss-120b", "Qwen3-32B", "Qwen3-8B"][(i + d) % 3],
        category: categories[(i + d * 2) % 6],
        questions,
        chats: Math.ceil(questions / 3),
        attachments: (i + d) % 4 === 0 ? Math.ceil(questions / 3) : 0,
        requests: questions + ((i + d) % 4 === 0 ? 1 : 0),
        prompt,
        completion,
        spend: (prompt * 0.15 + completion * 0.6) / 1e6,
      });
    }
    usage.push({
      date,
      userId: null,
      model: "gpt-oss-120b",
      category: "미분류",
      questions: 0,
      chats: 0,
      attachments: 0,
      requests: 3,
      prompt: 3000,
      completion: 600,
      spend: 0.00081,
    });
  }
  return {
    schemaVersion: 1,
    source: "mock",
    updatedAt: "2026-10-21T09:20:00+09:00",
    coverageStart: "2026-07-30",
    coverageEnd: "2026-10-21",
    users,
    usage,
    cache: { logs: 82522, classified: 75642, pending: 148 },
    operations: [
      {
        id: "demo-run-01",
        kind: "빠른 업데이트",
        startedAt: "2026-10-21T09:18:00+09:00",
        status: "success",
        steps: [
          {
            name: "OpenWebUI DB 스냅샷",
            status: "success",
            detail: "무결성 검사 및 분석 DB 반영 완료",
          },
          {
            name: "토큰 로그 동기화",
            status: "success",
            detail: "신규 로그 248건 · 중복 요청 제외",
          },
          {
            name: "질문 카테고리 분류",
            status: "success",
            detail: "신규 질문 96건 분류 완료",
          },
        ],
      },
    ],
  };
}
