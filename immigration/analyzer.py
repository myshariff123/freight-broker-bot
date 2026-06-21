import json
import logging
import os
from typing import Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

_client: AsyncAnthropic = None


def get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    return _client


SYSTEM = (
    "You are a senior Canadian immigration policy analyst with 20 years of experience. "
    "You assist Regulated Canadian Immigration Consultants (RCICs) and immigration lawyers "
    "by analyzing policy changes from IRCC and all provincial immigration authorities. "
    "Your analysis must be precise, actionable, and grounded in Canadian immigration law. "
    "Respond ONLY with valid JSON — no markdown fences, no commentary."
)

PROMPT = """\
A content change was detected on a Canadian immigration website. Analyse it carefully.

SOURCE: {name}
CATEGORY: {category}
PROVINCE: {province}
URL: {url}

PAGE CONTENT (current):
{content}

Return ONLY a JSON object with these exact keys:

{{
  "is_meaningful_change": true or false,
  "summary": "2-3 sentence plain-English summary of exactly what changed",
  "impact_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "sentiment": "POSITIVE|NEGATIVE|NEUTRAL",
  "affected_case_types": [subset of: "EXPRESS_ENTRY_FSW","EXPRESS_ENTRY_CEC","EXPRESS_ENTRY_FST","PNP_GENERAL","FAMILY_SPOUSE","FAMILY_PARENTS","FAMILY_CHILDREN","STUDY_PERMIT","PGWP","OPEN_WORK_PERMIT","TFWP_LMIA","IMP_NO_LMIA","VISITOR_VISA","REFUGEE_CLAIM","CITIZENSHIP","PR_CARD_RENEWAL","STARTUP_VISA","CAREGIVER","ATLANTIC_PROGRAM"],
  "affected_provinces": ["AB","BC","ON",...] or ["ALL"],
  "what_changed_detail": "Specific change with exact numbers, dates, thresholds where visible",
  "rcic_immediate_actions": ["Action 1 RCIC must take", "Action 2", ...],
  "client_impact": "How active clients in affected streams are impacted right now",
  "deadline_sensitive": true or false,
  "deadline_details": "Specific deadline and what it applies to, or null",
  "positive_aspects": "Beneficial aspects for applicants, or null",
  "negative_aspects": "Restrictive or concerning aspects, or null",
  "affected_applicant_profiles": "Which type of applicants/cases are most affected"
}}

Impact level guide:
CRITICAL — Program suspension, emergency deadline, major eligibility overhaul affecting thousands
HIGH     — New stream opening/closing, CRS score change, significant policy shift
MEDIUM   — Processing time update, minor eligibility tweak, form/document changes
LOW      — Administrative notice, website restructure, general information only

Set is_meaningful_change to false for: navigation-only changes, date/footer updates, cookie notices.
Be direct and specific. RCICs act on this within minutes of receiving it."""


async def analyze_change(
    name: str, url: str, category: str, province: Optional[str], content: str
) -> dict:
    from typing import Optional  # avoid circular at module level
    prompt = PROMPT.format(
        name=name,
        category=category,
        province=province or "Federal",
        url=url,
        content=content[:3500],
    )
    try:
        resp = await get_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1600,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error from Claude: {e} | raw: {raw[:300]}")
        return _fallback_analysis(name, content)
    except Exception as e:
        logger.error(f"Claude API error: {e}")
        raise


def _fallback_analysis(name: str, content: str) -> dict:
    return {
        "is_meaningful_change": True,
        "summary": f"Change detected on {name}. Automated analysis failed — manual review required.",
        "impact_level": "MEDIUM",
        "sentiment": "NEUTRAL",
        "affected_case_types": [],
        "affected_provinces": ["ALL"],
        "what_changed_detail": content[:400],
        "rcic_immediate_actions": ["Review the source URL manually for details"],
        "client_impact": "Unknown — please review source directly",
        "deadline_sensitive": False,
        "deadline_details": None,
        "positive_aspects": None,
        "negative_aspects": None,
        "affected_applicant_profiles": "Unknown",
    }
