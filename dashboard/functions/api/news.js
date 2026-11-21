export async function onRequest(context) {
    const { env } = context;
    const info = await env.DB.prepare("SELECT * FROM news ORDER BY timestamp DESC LIMIT 10").all();
    return new Response(JSON.stringify(info.results), {
        headers: { "Content-Type": "application/json" }
    });
}
