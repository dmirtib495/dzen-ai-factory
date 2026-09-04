type Env = {
  DB: D1Database;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  CONTROL_SECRET: string;
};

type TgUpdate = any;

const json = (data: unknown, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });

async function tg(env: Env, method: string, body: Record<string, unknown>) {
  if (!env.TELEGRAM_BOT_TOKEN) {
    console.error("TELEGRAM_BOT_TOKEN is missing");
    return { ok: false, description: "TELEGRAM_BOT_TOKEN is missing" };
  }

  const r = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }
  );

  const text = await r.text();
  let data: any;
  try {
    data = JSON.parse(text);
  } catch {
    data = { ok: false, description: text };
  }

  console.log(`Telegram API ${method}: HTTP ${r.status}, ok=${String(data?.ok)}`);
  if (!r.ok || !data?.ok) {
    console.error(`Telegram API error ${method}:`, JSON.stringify(data));
  }
  return data;
}

async function send(env: Env, chatId: string, text: string, keyboard?: unknown) {
  console.log(`sendMessage requested for chat=${chatId}, textLength=${text.length}`);
  const body: Record<string, unknown> = {
    chat_id: chatId,
    text: text.slice(0, 4096),
  };
  if (keyboard) body.reply_markup = keyboard;
  const result = await tg(env, "sendMessage", body);
  if (!result?.ok) console.error("sendMessage failed:", JSON.stringify(result));
  return result;
}

function menu() {
  return {
    inline_keyboard: [
      [
        { text: "📋 Очередь", callback_data: "queue" },
        { text: "📊 Аналитика", callback_data: "analytics" },
      ],
      [
        { text: "🧠 Стратегия", callback_data: "strategy" },
        { text: "📈 Лимит AI", callback_data: "quota" },
      ],
      [
        { text: "ℹ️ Генерация", callback_data: "generate" },
        { text: "🔄 Обновить", callback_data: "status" },
      ],
    ],
  };
}

async function queue(env: Env) {
  const r = await env.DB.prepare(`
    SELECT id, headline, category, status, created_at
    FROM articles
    WHERE status IN ('queued', 'needs_review')
    ORDER BY id DESC
    LIMIT 10
  `).all();

  if (!r.results?.length) return "📭 Очередь пуста.";

  return "📋 Очередь:\n" + r.results
    .map((x: any) => `• #${x.id} — ${x.headline}\n  ${x.category || ""} · ${x.status}`)
    .join("\n");
}

async function analytics(env: Env) {
  const r = await env.DB.prepare(`
    SELECT a.id,a.headline,a.category,
      COALESCE(m.views,0) views,
      COALESCE(m.likes,0) likes,
      COALESCE(m.comments,0) comments,
      COALESCE(m.shares,0) shares
    FROM articles a
    LEFT JOIN metrics m ON m.article_id=a.id
    ORDER BY views DESC
    LIMIT 5
  `).all();

  if (!r.results?.length) return "📊 Пока нет статистики.";

  return "📊 Топ материалов:\n" + r.results.map((x: any) => {
    const er = (((Number(x.likes || 0) + Number(x.comments || 0) * 2 + Number(x.shares || 0) * 3) /
      Math.max(Number(x.views || 0), 1)) * 100).toFixed(2);
    return `• ${x.views} просмотров · ER ${er}%\n${x.headline}`;
  }).join("\n\n");
}

async function strategy(env: Env) {
  const r = await env.DB.prepare("SELECT key,value FROM settings WHERE key='strategy'").first<any>();
  if (!r) return "🧠 Стратегия ещё не рассчитана. Она обновится после появления статистики.";
  try {
    const s = JSON.parse(r.value);
    const rows = Object.entries(s.categories || {}).sort((a: any,b: any) => (b[1].weight||0)-(a[1].weight||0));
    return "🧠 Стратегия категорий:\n" + rows.map(([k,v]: any) => `• ${k}: вес ${v.weight} · статей ${v.articles} · ср. просмотры ${v.avg_views}`).join("\n");
  } catch {
    return "🧠 Стратегия повреждена — будет пересчитана следующим запуском.";
  }
}

async function quota(env: Env) {
  const day = new Date().toISOString().slice(0,10);
  const row = await env.DB.prepare("SELECT requests FROM ai_usage WHERE day=?").bind(day).first<any>();
  const used = Number(row?.requests || 0), limit = 50;
  return `📈 OpenRouter\nИспользовано сегодня: ${used}\nОсталось: ${Math.max(0,limit-used)}\nЛимит фабрики: ${limit}`;
}

async function articleText(env: Env, id: number) {
  return env.DB.prepare("SELECT headline,category,article_markdown,source_urls_json,fact_check_json,status FROM articles WHERE id=?").bind(id).first<any>();
}

async function handleCallback(env: Env, chat: string, data: string, callbackId: string) {
  console.log(`callback received: chat=${chat}, data=${data}`);
  await tg(env, "answerCallbackQuery", { callback_query_id: callbackId });
  if (data === "queue") return send(env, chat, await queue(env), menu());
  if (data === "analytics") return send(env, chat, await analytics(env), menu());
  if (data === "strategy") return send(env, chat, await strategy(env), menu());
  if (data === "quota") return send(env, chat, await quota(env), menu());
  if (data === "status") {
    const c = await env.DB.prepare("SELECT COUNT(*) n FROM articles WHERE status IN ('queued','needs_review')").first<any>();
    return send(env, chat, `🟢 Dzen AI Factory Cloud\nВ очереди: ${c?.n || 0}\n${await quota(env)}`, menu());
  }
  if (data === "generate") {
    return send(env, chat, "🚗 Автоматическая генерация выполняется через GitHub Actions по расписанию 06:00, 12:00 и 18:00 по Москве.", menu());
  }

  const m = /^approve:(\d+)$/.exec(data);
  if (m) {
    const id = Number(m[1]);
    await env.DB.prepare("UPDATE articles SET status='approved',updated_at=? WHERE id=?").bind(new Date().toISOString(), id).run();
    return send(env, chat, `✅ Материал #${id} одобрен. Публикация остаётся отдельным официальным шагом Дзена.`, menu());
  }

  const rej = /^reject:(\d+)$/.exec(data);
  if (rej) {
    const id = Number(rej[1]);
    await env.DB.prepare("UPDATE articles SET status='rejected',updated_at=? WHERE id=?").bind(new Date().toISOString(), id).run();
    return send(env, chat, `❌ Материал #${id} отклонён.`, menu());
  }

  const txt = /^text:(\d+)$/.exec(data);
  if (txt) {
    const id = Number(txt[1]);
    const a = await articleText(env,id);
    if (!a) return send(env,chat,"Материал не найден.",menu());
    return send(env,chat,`📝 ${a.headline}\n\nКатегория: ${a.category}\n\n${a.article_markdown}\n\nИсточники: ${a.source_urls_json}\n\nПроверка: ${a.fact_check_json}`,menu());
  }
}

async function handleUpdate(env: Env, u: TgUpdate) {
  console.log("Telegram update received:", JSON.stringify({
    update_id: u?.update_id,
    has_message: Boolean(u?.message),
    has_callback_query: Boolean(u?.callback_query),
  }));

  if (u.callback_query) {
    const cb = u.callback_query;
    const chat = String(cb.message?.chat?.id || "");
    const allowedChat = String(env.TELEGRAM_CHAT_ID || "").trim();
    console.log(`callback chat check: incoming=${chat}, configured=${allowedChat ? "set" : "missing"}, match=${chat === allowedChat}`);
    if (allowedChat && chat !== allowedChat) {
      console.warn(`callback rejected by TELEGRAM_CHAT_ID check: incoming=${chat}`);
      return;
    }
    return handleCallback(env, chat, String(cb.data || ""), cb.id);
  }

  const m = u.message;
  if (!m) {
    console.log("Update has no message; ignored");
    return;
  }

  const chat = String(m?.chat?.id || "");
  const text = String(m?.text || "").trim();
  const allowedChat = String(env.TELEGRAM_CHAT_ID || "").trim();

  console.log(`message received: chat=${chat}, text=${text || "(empty)"}, configuredChat=${allowedChat ? "set" : "missing"}, match=${chat === allowedChat}`);

  if (allowedChat && chat !== allowedChat) {
    console.warn(`message rejected by TELEGRAM_CHAT_ID check: incoming=${chat}`);
    return;
  }

  if (["/start", "/help"].includes(text)) {
    console.log("Handling /start or /help");
    return send(env, chat, "🤖 Dzen AI Factory Cloud\nУправление фабрикой:", menu());
  }
  if (text === "/queue") return send(env, chat, await queue(env), menu());
  if (text === "/status") return send(env, chat, `🟢 Dzen AI Factory Cloud\n${await quota(env)}`, menu());
  if (text === "/analytics") return send(env, chat, await analytics(env), menu());
  if (text === "/strategy") return send(env, chat, await strategy(env), menu());
  if (text === "/limits") return send(env, chat, await quota(env), menu());

  console.log(`Unknown command ignored: ${text}`);
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);

    if (url.pathname === "/health") {
      return json({
        ok: true,
        service: "dzen-auto-control",
        telegram_token_configured: Boolean(env.TELEGRAM_BOT_TOKEN),
        telegram_chat_configured: Boolean(env.TELEGRAM_CHAT_ID),
        d1_configured: Boolean(env.DB),
      });
    }

    if (url.pathname === "/telegram/webhook" && req.method === "POST") {
      try {
        const u = await req.json<TgUpdate>();
        await handleUpdate(env, u);
        return json({ ok: true });
      } catch (error: any) {
        console.error("Webhook handler error:", error?.stack || error?.message || String(error));
        return json({ ok: false, error: "webhook_handler_error" }, 500);
      }
    }

    if (url.pathname === "/set-webhook" && req.method === "POST") {
      const secret = req.headers.get("x-control-secret");
      if (!env.CONTROL_SECRET || secret !== env.CONTROL_SECRET) {
        return json({ error: "unauthorized" }, 401);
      }
      const hook = `${url.origin}/telegram/webhook`;
      return json(await tg(env, "setWebhook", { url: hook, drop_pending_updates: true }));
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
