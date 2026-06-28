"""질문 카테고리 분류 로직.

초기 버전은 유지보수하기 쉬운 키워드 기반 규칙으로 시작합니다.
향후 사내 LLM 분류 방식으로 바꿔도 화면 코드에는 영향이 없도록
서비스 모듈로 분리해 둡니다.
"""

from __future__ import annotations


CATEGORY_KEYWORDS = {
    "문서 검색/RAG": ["문서", "자료", "근거", "검색", "찾아", "출처"],
    "요약": ["요약", "정리", "핵심", "줄여"],
    "번역/문장 작성": ["번역", "영문", "국문", "작성", "메일", "문장"],
    "코드/개발": ["코드", "파이썬", "python", "sql", "api", "오류", "에러"],
    "업무 지식 질의": ["규정", "절차", "업무", "프로세스", "정책"],
}


def classify_question(content: str) -> str:
    normalized = (content or "").lower()

    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword.lower() in normalized for keyword in keywords):
            return category

    return "일반 질의" if normalized.strip() else "기타"
