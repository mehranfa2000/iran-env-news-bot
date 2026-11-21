export async function onRequest(context) {
    const { env } = context;
    // کوئری برای گرفتن آمار کلی
    const info = await env.DB.prepare("SELECT category, count(*) as count FROM news GROUP BY category").all();
    return new Response(JSON.stringify(info.results), {
        headers: { "Content-Type": "application/json" }
    });
}
