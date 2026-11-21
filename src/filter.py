# ============================================================
# سیستم فیلتر ۳ لایه اخبار محیط زیست
# لایه ۱: بررسی لیست سیاه
# لایه ۲: امتیازدهی وزنی (عنوان=۳ امتیاز، متن=۱ امتیاز)
# لایه ۳: حداقل آستانه ۴ امتیاز
# ============================================================

from src.keywords import KEYWORDS, BLACKLIST, CATEGORY_INFO

def filter_and_categorize(news_item):
    """
    خبر را فیلتر و دسته‌بندی می‌کند.
    اگر خبر مرتبط باشد: news_item غنی‌شده برمی‌گردد.
    اگر نامرتبط باشد: None برمی‌گردد.
    """
    title   = news_item.get("title", "")
    summary = news_item.get("summary", "")
    
    # برای فیدهای اختصاصی محیط زیست، آستانه پایین‌تر است
    min_threshold = 2 if news_item.get("dedicated", False) else 4

    # ============================================================
    # لایه ۱: بررسی لیست سیاه
    # ============================================================
    full_text = title + " " + summary
    for bad_word in BLACKLIST:
        if bad_word in full_text:
            # اگر کلمه سیاه در عنوان بود، رد کن
            if bad_word in title:
                return None

    # ============================================================
    # لایه ۲: امتیازدهی وزنی
    # ============================================================
    scores = {}
    matched_keywords = {}

    for cat, words in KEYWORDS.items():
        score = 0
        matches = []
        for word in words:
            # امتیاز ۳ برای هر بار تکرار در عنوان
            title_count = title.count(word)
            # امتیاز ۱ برای هر بار تکرار در خلاصه
            summary_count = summary.count(word)
            
            word_score = (title_count * 3) + (summary_count * 1)
            if word_score > 0:
                score += word_score
                matches.append(word)
        
        if score > 0:
            scores[cat] = score
            matched_keywords[cat] = matches

    # ============================================================
    # لایه ۳: بررسی آستانه
    # ============================================================
    if not scores:
        return None

    # انتخاب دسته با بیشترین امتیاز
    best_cat = max(scores, key=scores.get)
    best_score = scores[best_cat]

    if best_score < min_threshold:
        return None

    # اضافه کردن اطلاعات دسته‌بندی به خبر
    cat_info = CATEGORY_INFO.get(best_cat, {"fa": best_cat, "emoji": "🌱"})
    
    news_item["category"]    = best_cat
    news_item["category_fa"] = cat_info["fa"]
    news_item["emoji"]       = cat_info["emoji"]
    news_item["score"]       = best_score
    news_item["keywords"]    = matched_keywords.get(best_cat, [])

    return news_item
