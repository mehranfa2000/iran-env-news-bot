from src.keywords import KEYWORDS, BLACKLIST

def get_category_emoji(cat_name):
    emojis = {
        "air_pollution": "🌬️", "wildlife": "🐆", "water_wetlands": "🌊",
        "climate_change": "🌡️", "forests": "🌲", "policy_org": "🏛️",
        "sustainable_dev": "♻️"
    }
    return emojis.get(cat_name, "🌱")

def filter_and_categorize(news_item):
    text = (news_item['title'] + " " + news_item['summary']).lower()
    
    # بررسی لیست سیاه
    for word in BLACKLIST:
        if word in text:
            return None

    scores = {}
    for cat, words in KEYWORDS.items():
        score = 0
        for word in words:
            # امتیاز ۳ برای تکرار در عنوان، امتیاز ۱ برای متن
            score += (news_item['title'].count(word) * 3)
            score += (news_item['summary'].count(word) * 1)
        if score > 0:
            scores[cat] = score

    if not scores:
        return None

    # انتخاب دسته‌ای که بیشترین امتیاز را دارد
    best_cat = max(scores, key=scores.get)
    
    # حد آستانه امتیاز (حداقل ۴ امتیاز برای تایید نهایی)
    if scores[best_cat] >= 4:
        news_item['category'] = best_cat
        news_item['emoji'] = get_category_emoji(best_cat)
        return news_item
    
    return None
