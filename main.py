import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import requests

# 환경 변수 (GitHub Secrets)
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_KEY = os.environ.get("GMAIL_APP_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

URLS = {
    "인하대 메인 공지": "https://www.inha.ac.kr/kr/950/subview.do",
    "신소재공학과 공지": "https://dmse.inha.ac.kr/dmse/2121/subview.do",
}

EXCLUDE_KEYWORDS = ["백서", "발간", "소식지", "뉴스레터", "설문", "조사"]
TARGET_RULES = {
    "반도체/신소재 프로젝트·대외활동": (
        ["반도체", "신소재", "소재", "나노"],
        [
            "프로젝트",
            "경진대회",
            "공모전",
            "해커톤",
            "대외활동",
            "인턴",
            "교육",
            "실습",
            "부트캠프",
            "멘토링",
        ],
    ),
    "반도체/신소재 세미나·강연": (
        ["반도체", "신소재", "소재", "나노"],
        [
            "강연",
            "세미나",
            "학술대회",
            "특강",
            "포럼",
            "심포지엄",
            "워크숍",
            "설명회",
        ],
    ),
    "데이터 분석 프로젝트·대외활동": (
        ["데이터", "빅데이터", "인공지능", "AI"],
        ["분석", "프로젝트", "경진대회", "공모전", "교육"],
    ),
    "장학금": (["장학", "장학생", "등록금", "학자금"], []),
    "필수 학사/졸업": (
        [
            "수강신청",
            "졸업요건",
            "졸업사정",
            "졸업논문",
            "조기졸업",
            "학위증서",
            "학위수여식",
            "성적공시",
            "수강변경",
        ],
        [],
    ),
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )
}
HISTORY_FILE = "seen_notices.json"


def summarize_with_gemini(title, body_text):
  """Gemini AI에게 공지 본문을 전달하여 핵심 일정 및 3줄 요약 생성"""
  if not GEMINI_API_KEY:
    return body_text[:160] + "...", "일정 정보 본문 참조"

  endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
  prompt = f"""
    당신은 대학생을 위한 학사/공지 전문 분석 AI 비서입니다.
    아래 대학교 공지사항의 제목과 본문을 읽고, 지원 대상 학생이 한눈에 파악할 수 있도록 핵심을 요약해주세요.

    [공지 제목]: {title}
    [공지 본문]:
    {body_text[:2500]}

    반드시 아래 JSON 형식으로만 순수 텍스트(Markdown 코드블록 없이)로 출력하세요:
    {{
      "deadline": "정확한 마감/신청/운영 기간 (연도.월.일 형식 포함, 없으면 '상세 본문 참조')",
      "target": "지원 대상 및 자격 요건 (1문장)",
      "bullets": [
        "핵심 내용 요약 1",
        "핵심 내용 요약 2",
        "핵심 내용 요약 3"
      ]
    }}
    """
  try:
    res = requests.post(
        endpoint,
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=15,
    )
    res_data = res.json()
    raw_response = res_data["candidates"][0]["content"]["parts"][0][
        "text"
    ].strip()
    clean_json = (
        raw_response.replace("```json", "").replace("```", "").strip()
    )
    data = json.loads(clean_json)
    return data
  except Exception as e:
    print(f"Gemini API 호출 예외: {e}")
    return {
        "deadline": "공지 본문 참조",
        "target": "상세 내용 확인",
        "bullets": [body_text[:160] + "..."],
    }


def classify_title(title):
  for ex in EXCLUDE_KEYWORDS:
    if ex in title:
      return None
  matched = []
  for cat_name, (kws1, kws2) in TARGET_RULES.items():
    if not kws2:
      if any(k in title for k in kws1):
        matched.append(cat_name)
    else:
      if any(k1 in title for k1 in kws1) and any(k2 in title for k2 in kws2):
        matched.append(cat_name)
  return matched if matched else None


def fetch_all_notices():
  collected = []
  for site_name, base_url in URLS.items():
    domain = (
        "https://www.inha.ac.kr"
        if "inha.ac.kr/kr" in base_url
        else "https://dmse.inha.ac.kr"
    )
    try:
      res = requests.get(base_url, headers=HEADERS, timeout=10)
      res.encoding = "utf-8"
      soup = BeautifulSoup(res.text, "html.parser")
      links = soup.select(
          "td.td-subject a, .artclTableTtitle a, a.artclLinkView, .board-list a"
      )

      for a_tag in links:
        title = " ".join(a_tag.get_text().split())
        raw_href = a_tag.get("href", "")
        if not raw_href or len(title) < 3:
          continue
        if raw_href.startswith("http"):
          full_url = raw_href
        elif raw_href.startswith("/"):
          full_url = domain + raw_href
        else:
          full_url = base_url.split("?")[0] + raw_href

        matched = classify_title(title)
        if matched:
          collected.append({
              "site": site_name,
              "title": title,
              "link": full_url,
              "categories": matched,
          })
    except Exception as e:
      print(f"Error fetching {site_name}: {e}")
  return collected


def get_notice_body(detail_url):
  try:
    res = requests.get(detail_url, headers=HEADERS, timeout=10)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")
    body_elem = soup.select_one(
        ".artclView, .view-con, .view-content, .board-view-content"
    )
    return " ".join(body_elem.get_text().split()) if body_elem else ""
  except Exception:
    return ""


def send_email(subject, html_content):
  if not GMAIL_USER or not GMAIL_APP_KEY:
    return
  msg = MIMEMultipart("alternative")
  msg["Subject"] = subject
  msg["From"] = f"인하대 AI 공지 알리미 <{GMAIL_USER}>"
  msg["To"] = GMAIL_USER
  msg.attach(MIMEText(html_content, "html", "utf-8"))

  with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, GMAIL_APP_KEY)
    server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
  print("✅ 이메일 발송 완료")


def main():
  seen_notices = set()
  if os.path.exists(HISTORY_FILE):
    try:
      with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        seen_notices = set(json.load(f))
    except Exception:
      pass

  current_notices = fetch_all_notices()
  new_items = []

  for item in current_notices:
    if item["link"] not in seen_notices:
      body_text = get_notice_body(item["link"])
      ai_result = summarize_with_gemini(item["title"], body_text)
      item["ai_data"] = ai_result
      new_items.append(item)
      seen_notices.add(item["link"])

  with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(list(seen_notices), f, ensure_ascii=False, indent=2)

  if new_items:
    subject = f"🤖 [AI 브리핑] 인하대 맞춤 신규 공지 {len(new_items)}건"
    html = """
        <div style="font-family: Arial, sans-serif; max-width: 620px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h2 style="color: #0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">🤖 인하대 AI 핵심 공지 브리핑</h2>
        """
    for idx, n in enumerate(new_items, 1):
      ai = n["ai_data"]
      bullets_html = "".join([
          f"<li style='margin-bottom: 4px;'>{b}</li>"
          for b in ai.get("bullets", [])
      ])
      html += f"""
            <div style="margin-bottom: 22px; padding: 14px; background-color: #f8f9fa; border-left: 4px solid #0b57d0; border-radius: 4px;">
                <span style="background-color: #0b57d0; color: white; padding: 3px 8px; font-size: 11px; border-radius: 3px; font-weight: bold;">{', '.join(n['categories'])}</span>
                <h3 style="margin: 8px 0; font-size: 15px; color: #202124;">{idx}. {n['title']}</h3>
                <p style="margin: 4px 0; font-size: 13px; color: #d93025;"><strong>📅 일정:</strong> {ai.get('deadline', '본문 참조')}</p>
                <p style="margin: 4px 0; font-size: 13px; color: #1e8e3e;"><strong>🎯 대상:</strong> {ai.get('target', '상세 확인')}</p>
                <div style="margin-top: 8px; font-size: 13px; color: #3c4043; line-height: 1.5;">
                    <strong>📝 AI 핵심 요약:</strong>
                    <ul style="margin: 4px 0 0 16px; padding: 0;">{bullets_html}</ul>
                </div>
                <div style="margin-top: 10px;">
                    <a href="{n['link']}" target="_blank" style="display: inline-block; padding: 6px 12px; background-color: #1a73e8; color: white; text-decoration: none; border-radius: 4px; font-size: 12px; font-weight: bold;">원문 공지 바로가기 →</a>
                </div>
            </div>
            """
    html += "</div>"
    send_email(subject, html)
  else:
    print("새로운 맞춤 공지 없음.")


if __name__ == "__main__":
  main()
