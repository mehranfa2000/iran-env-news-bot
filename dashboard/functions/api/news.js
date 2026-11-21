export async function onRequest(context) {
    const { env, request } = context;
    try {
        const url    = new URL(request.url);
        const page   = parseInt(url.searchParams.get("page") || "1");
        const limit  = parseInt(url.searchParams.get("limit") || "20");
        const search = url.searchParams.get("q") || "";
        const offset = (page - 1) * limit;

        let sql, params;

        if (search) {
            sql = `SELECT * FROM news WHERE title LIKE ? OR source_fa LIKE ? OR category_fa LIKE ? ORDER BY timestamp DESC LIMIT ? OFFSET ?`;
            const q = `%${search}%`;
            params = [q, q, q, limit, offset];
        } else {
            sql    = `SELECT * FROM news ORDER BY timestamp DESC LIMIT ? OFFSET ?`;
            params = [limit, offset];
        }

        const result = await env.DB.prepare(sql).bind(...params).all();
        const countResult = await env.DB.prepare("SELECT count(*) as total FROM news").first();

        return new Response(JSON.stringify({
            news:  result.results,
            total: countResult?.total || 0,
            page,
            limit
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
