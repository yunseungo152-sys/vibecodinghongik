import json

import streamlit as st
from openai import OpenAI
from pypdf import PdfReader
from supabase import Client, create_client


st.set_page_config(page_title="AI 학습 정리 노트", page_icon="📚", layout="wide")
st.session_state.setdefault("summary", None)
st.session_state.setdefault("summary_record_id", None)
st.session_state.setdefault("quiz", None)


@st.cache_resource
def get_supabase_client() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

with st.sidebar:
    st.header("문서 업로드")
    uploaded_file = st.file_uploader(
        "PDF 파일을 업로드하세요",
        type=["pdf"],
        accept_multiple_files=False,
    )

if uploaded_file is not None:
    reader = PdfReader(uploaded_file)
    page_count = len(reader.pages)

    with st.sidebar:
        st.subheader("문서 정보")
        st.write(f"**파일명:** {uploaded_file.name}")
        st.metric("총 페이지 수", f"{page_count}페이지")

st.title("AI 학습 정리 노트")

original_tab, summary_tab, quiz_tab, history_tab = st.tabs(
    ["원문", "요약", "퀴즈", "저장 기록"]
)
with original_tab:
    if uploaded_file is None:
        st.info("사이드바에서 PDF 파일을 업로드하세요.")
    else:
        st.subheader("페이지별 추출 텍스트")
        for page_number, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or "(이 페이지에서는 추출할 텍스트가 없습니다.)"
            with st.expander(f"{page_number}페이지", expanded=page_number == 1):
                st.text_area(
                    f"{page_number}페이지 내용",
                    page_text,
                    height=300,
                    label_visibility="collapsed",
                    key=f"page-text-{page_number}",
                )

with summary_tab:
    if uploaded_file is None:
        st.info("요약하려면 사이드바에서 PDF 파일을 업로드하세요.")
    else:
        st.subheader("AI 요약")
        if st.button("요약하기", type="primary"):
            full_text = "\n\n".join(
                page.extract_text() or ""
                for page in reader.pages
            ).strip()

            if not full_text:
                st.warning("요약할 텍스트가 PDF에 없습니다.")
            else:
                system_prompt = (
                    "다음 PDF 텍스트를 분석하고 반드시 JSON 객체로만 반환하세요. "
                    'JSON 필드는 "핵심 요약", "주요 키워드", "난이도"를 사용하세요. '
                    '"핵심 요약"은 정확히 3문장, "주요 키워드"는 정확히 5개, '
                    '"난이도"는 "상", "중", "하" 중 하나로 작성하세요.'
                )

                try:
                    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                    response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": full_text},
                        ],
                        response_format={"type": "json_object"},
                    )
                    response_content = response.choices[0].message.content or "{}"
                    st.session_state["summary"] = json.loads(response_content)
                except KeyError:
                    st.error("OpenAI API 키가 설정되지 않았습니다. .streamlit/secrets.toml을 확인하세요.")
                except Exception as error:
                    st.error(f"요약 중 오류가 발생했습니다: {error}")

        if st.session_state["summary"] is not None:
            summary = st.session_state["summary"]
            st.markdown("**핵심 요약**")
            st.write(summary.get("핵심 요약", "요약 내용이 없습니다."))
            st.markdown("**주요 키워드**")
            keywords = summary.get("주요 키워드", [])
            st.write(", ".join(keywords) if isinstance(keywords, list) else keywords)
            st.markdown("**난이도**")
            st.write(summary.get("난이도", "난이도 정보가 없습니다."))

            if st.button("저장"):
                try:
                    supabase = get_supabase_client()
                    insert_response = supabase.table("summaries").insert(
                        {
                            "filename": uploaded_file.name,
                            "summary": summary,
                        }
                    ).execute()
                    st.session_state["summary_record_id"] = insert_response.data[0]["id"]
                    st.success("요약 결과를 저장했습니다.")
                except Exception as error:
                    st.error(f"요약 저장 중 오류가 발생했습니다: {error}")

with quiz_tab:
    if st.session_state["summary"] is None:
        st.info("퀴즈를 만들려면 먼저 요약 탭에서 요약을 생성하세요.")
    else:
        st.subheader("학습 퀴즈")
        if st.button("퀴즈 생성", type="primary"):
            quiz_system_prompt = """당신은 학습 퀴즈를 만드는 도우미입니다.
주어진 요약을 바탕으로 4지선다 퀴즈 3문항을 만드세요.
각 문항은 question, options(4개), answer(정답 인덱스, 0부터 시작), explanation을 포함해야 합니다.
결과는 {"questions": [...]} 형태의 JSON으로 반환하세요.
"""
            try:
                client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": quiz_system_prompt},
                        {
                            "role": "user",
                            "content": json.dumps(
                                st.session_state["summary"], ensure_ascii=False
                            ),
                        },
                    ],
                    response_format={"type": "json_object"},
                )
                response_content = response.choices[0].message.content or "{}"
                quiz = json.loads(response_content)
                st.session_state["quiz"] = quiz

                if st.session_state["summary_record_id"] is None:
                    st.warning("요약 결과를 먼저 저장해주세요.")
                else:
                    get_supabase_client().table("summaries").update(
                        {"quiz": quiz}
                    ).eq("id", st.session_state["summary_record_id"]).execute()
                    st.success("퀴즈를 저장된 요약 기록에 반영했습니다.")
            except KeyError:
                st.error("OpenAI API 키가 설정되지 않았습니다. .streamlit/secrets.toml을 확인하세요.")
            except Exception as error:
                st.error(f"퀴즈 생성 중 오류가 발생했습니다: {error}")

        if st.session_state["quiz"] is not None:
            questions = st.session_state["quiz"].get("questions", [])
            for question_number, question in enumerate(questions, start=1):
                st.markdown(f"**{question_number}. {question['question']}**")
                selected_option = st.radio(
                    "보기",
                    question["options"],
                    index=None,
                    key=f"quiz-question-{question_number}",
                    label_visibility="collapsed",
                )
                if selected_option is not None:
                    selected_index = question["options"].index(selected_option)
                    if selected_index == question["answer"]:
                        st.success("정답입니다!")
                    else:
                        st.error("오답입니다.")
                    st.info(f"해설: {question['explanation']}")

with history_tab:
    st.subheader("저장 기록")
    try:
        supabase = get_supabase_client()
        records = (
            supabase.table("summaries")
            .select("id, filename, summary, created_at")
            .order("created_at", desc=True)
            .execute()
            .data
        )

        if not records:
            st.info("저장된 요약 기록이 없습니다.")
        else:
            for record in records:
                summary_data = record.get("summary") or {}
                summary_text = summary_data.get("핵심 요약", "")
                if len(summary_text) > 120:
                    summary_text = f"{summary_text[:120]}..."

                record_col, delete_col = st.columns([5, 1])
                with record_col:
                    st.markdown(f"**{record.get('filename', '이름 없음')}**")
                    st.caption(
                        f"저장 시각: {record.get('created_at', '알 수 없음')}\n\n"
                        f"{summary_text or '핵심 요약이 없습니다.'}"
                    )
                with delete_col:
                    if st.button("삭제", key=f"delete-summary-{record['id']}"):
                        supabase.table("summaries").delete().eq(
                            "id", record["id"]
                        ).execute()
                        st.rerun()
                st.divider()
    except Exception as error:
        st.error(f"저장 기록을 불러오는 중 오류가 발생했습니다: {error}")
