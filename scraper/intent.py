"""
Rule-based intent scoring — deliberately NOT a black-box ML score, so you
can see exactly why a lead scored what it scored and tune the weights as
you see real outreach results come back.

All inputs are business-level public signals: the business's own Page
posting/bio, its Ad Library presence, and its Google review activity.
Nothing here touches a personal profile.
"""


def score_intent(business: dict) -> dict:
    """
    business is expected to carry (any may be missing/None — handled):
      review_count, rating, running_ads, dm_order_flow, checkout_present,
      owner_response_ratio, email (bool-ish), website (social link or None)

    Returns {"website_intent_score": int 1-10, "other_intents": [str,...], "intent_notes": str}
    """
    reasons = []
    s = 3.0  # baseline: they qualified as no-website already, that's worth something on its own

    running_ads = business.get("running_ads")
    dm_order_flow = business.get("dm_order_flow", False)
    checkout_present = business.get("checkout_present", False)
    owner_resp_ratio = business.get("owner_response_ratio")
    reviews = business.get("review_count") or 0
    rating = business.get("rating") or 0

    if running_ads is True:
        s += 3
        reasons.append("running Meta ads with no landing page — likely leaking paid-traffic conversions")
    elif running_ads is False:
        reasons.append("not currently running ads")
    # running_ads is None -> unverified, no adjustment, no claim made

    if dm_order_flow:
        s += 2.5
        reasons.append("bio signals manual DM/WhatsApp ordering — no real checkout flow")

    if checkout_present:
        s -= 2
        reasons.append("already has some online store/checkout link — lower first-website urgency")

    if owner_resp_ratio is not None:
        if owner_resp_ratio >= 0.5:
            s += 1
            reasons.append("actively responds to reviews — engaged, likely receptive to outreach")
        elif owner_resp_ratio == 0 and reviews >= 10:
            reasons.append("has reviews but never responds — reputation-management gap")

    if reviews >= 10 and rating >= 4.0:
        s += 1
        reasons.append("established, well-rated business — more likely to have budget")

    website_intent_score = max(1, min(10, round(s)))

    other_intents = []
    if running_ads is True:
        other_intents.append("Google/Meta ads management (already spending on ads, funnel needs a home)")
    if dm_order_flow and not checkout_present:
        other_intents.append("Simple ordering website + WhatsApp order automation")
    if owner_resp_ratio == 0 and reviews >= 10:
        other_intents.append("Review/reputation management")
    if checkout_present:
        other_intents.append("Website rebuild/upgrade rather than first website")
    if not other_intents:
        other_intents.append("Standalone website — no other strong signal yet")

    return {
        "website_intent_score": website_intent_score,
        "other_intents": other_intents,
        "intent_notes": "; ".join(reasons) if reasons else "no strong signals either way",
    }
