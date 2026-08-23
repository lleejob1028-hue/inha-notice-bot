import json
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
import requests

# 환경 변수 (GitHub Secrets에서 주입)
GMAIL_USER = os.environ.get("GMAIL_USER")
GMAIL_APP_KEY = os.environ.get("GMAIL_APP_KEY")

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


def extract_notice_details(detail_url):
  try:
    res = requests.get(detail_url, headers=HEADERS, timeout=10)
    res.encoding = "utf-8"
    soup = BeautifulSoup(res.text, "html.parser")
    body_elem = soup.select_one(
        ".artclView, .view-con, .view-content, .board-view-content"
    )
    if not body_elem:
      return "본문 상세는 링크를 참조하세요.", "본문 일정 참조"

    body_text = " ".join(body_elem.get_text().split())
    date_patterns = [
        r"(?:신청|접수|운영|제출|기한|기간|일시)\s*[:~]\s*([0-9]{4}[.\-/][0-9]{1,2}[.\-/][0-9]{1,2}.*?(?:[0-9]{1,2}:[0-9]{2}|~|\))?)",
        r"([0-9]{4}\.\s*[0-9]{1,2}\.\s*[0-9]{1,2}\s*\(.+?\)\s*~\s*[0-9]{4}\.\s*[0-9]{1,2}\.\s*[0-9]{1,2})",
        r"(~\s*[0-9]{4}[.\-/][0-9]{1,2}[.\-/][0-9]{1,2})",
    ]
    deadline_info = "본문 참조"
    for pattern in date_patterns:
      match = re.search(pattern, body_text)
      if match:
        deadline_info = match.group(0).strip()
        break
    summary = body_text[:160] + "..." if len(body_text) > 160 else body_text
    return summary, deadline_info
  except Exception:
    return "본문 로딩 실패", "확인 불가"


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


def send_email(subject, html_content):
  if not GMAIL_USER or not GMAIL_APP_KEY:
    print("이메일 환경변수가 없습니다.")
    return
  msg = MIMEMultipart("alternative")
  msg["Subject"] = subject
  msg["From"] = f"인하대 공지 알리미 <{GMAIL_USER}>"
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
      summary, deadline = extract_notice_details(item["link"])
      item["summary"] = summary
      item["deadline"] = deadline
      new_items.append(item)
      seen_notices.add(item["link"])

  with open(HISTORY_FILE, "w", encoding="utf-8") as f:
    json.dump(list(seen_notices), f, ensure_ascii=False, indent=2)

  if new_items:
    subject = f"🔔 [인하대/신소재] 새 맞춤 공지 {len(new_items)}건 도착"
    html = """
        <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
            <h2 style="color: #0b57d0; border-bottom: 2px solid #0b57d0; padding-bottom: 8px;">📢 새 맞춤 공지사항 알림</h2>
        """
    for idx, n in enumerate(new_items, 1):
      html += f"""
            <div style="margin-bottom: 20px; padding: 12px; background-color: #f8f9fa; border-radius: 6px;">
                <span style="background-color: #0b57d0; color: white; padding: 3px 8px; font-size: 12px; border-radius: 4px;">{', '.join(n['categories'])}</span>
                <h3 style="margin: 8px 0 6px 0; font-size: 16px; color: #202124;">{idx}. {n['title']}</h3>
                <p style="margin: 4px 0; font-size: 13px; color: #5f6368;"><strong>📅 일정:</strong> {n['deadline']}</p>
                <p style="margin: 6px 0; font-size: 13px; color: #3c4043; line-height: 1.4;">{n['summary']}</p>
                <a href="{n['link']}" target="_blank" style="display: inline-block; margin-top: 6px; padding: 6px 12px; background-color: #1a73e8; color: white; text-decoration: none; border-radius: 4px; font-size: 12px;">공지 본문 바로가기 →</a>
            </div>
            """
    html += "</div>"
    send_email(subject, html)
  else:
    print("새로운 맞춤 공지 없음.")


if __name__ == "__main__":
  main()
