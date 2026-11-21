export async function onRequest(context) {
    const { env } = context;
    try {
        const byCategory = await env.DB.prepare(
            "SELECT category, category_fa, emoji, count(*) as count FROM news GROUP BY category ORDER BY count DESC"
        ).all();

        const bySource = await env.DB.prepare(
            "SELECT source_fa, count(*) as count FROM news GROUP BY source_fa ORDER BY count DESC"
        ).all();

        const total = await env.DB.prepare(
            "SELECT count(*) as total FROM news"
        ).first();

        const today = await env.DB.prepare(
            "SELECT count(*) as today FROM news WHERE date(timestamp) = date('now')"
        ).first();

        return new Response(JSON.stringify({
            categories: byCategory.results,
            sources:    bySource.results,
            total:      total?.total || 0,
            today:      today?.today || 0
        }), {
            headers: {
                "Content-Type":                "application/json",
                "Access-Control-Allow-Origin": "*"
            }
        });
    } catch (e) {
        return new Response(JSON.stringify({ error: e.message }), { status: 500 });
    }
}
