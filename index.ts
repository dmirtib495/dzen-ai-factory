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

  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });

  const text = await r.text();
  let data: any;

  try {
    data = JSON.parse(text);
  } catch {
    data = { ok: false, description: text };
  }

  if (!r.ok || !data?.ok) {
    console.error(`Telegram API error ${method}:`, JSON.stringify(data));
  }

  return data;
}

async function send(env: Env, chatId: string, text: string, keyboard?: unknown) {
  const body: Record<string, unknown> = {
    chat_id: chatId,
    text: text.slice(0, 4096),
  };
  if (keyboard) body.reply_markup = keyboard;
  return tg(env, "sendMessage", body);
}

async function editMessage(
  env: Env,
  chatId: string,
  messageId: number,
  text: string,
  keyboard?: unknown
) {
  const body: Record<string, unknown> = {
    chat_id: chatId,
    message_id: messageId,
    text: text.slice(0, 4096),
  };
  if (keyboard) body.reply_markup = keyboard;
  return tg(env, "editMessageText", body);
}

function mainMenu() {
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
        { text: "ℹ️ Расписание", callback_data: "generate" },
        { text: "🔄 Статус", callback_data: "status" },
      ],
    ],
  };
}

function articleKeyboard(id: number, status: string) {
  const rows: any[] = [
    [{ text: "📝 Читать статью", callback_data: `text:${id}` }],
  ];

  if (status === "queued" || status === "needs_review") {
    rows.push([
      { text: "✅ Одобрить", callback_data: `approve:${id}` },
      { text: "❌ Отклонить", callback_data: `reject:${id}` },
    ]);
  }

  rows.push([
    { text: "⬅️ К очереди", callback_data: "queue" },
    { text: "🏠 Меню", callback_data: "menu" },
  ]);

  return { inline_keyboard: rows };
}

function queueKeyboard(items: any[]) {
  const rows = items.map((x: any) => [
    {
      text: `#${x.id} · ${String(x.headline).slice(0, 45)}`,
      callback_data: `article:${x.id}`,
    },
  ]);
  rows.push([{ text: "🏠 Главное меню", callback_data: "menu" }]);
  return { inline_keyboard: rows };
}

async function getQueue(env: Env) {
  return env.DB.prepare(
    "SELECT id,headline,category,status,created_at FROM articles WHERE status IN ('queued','needs_review') ORDER BY id DESC LIMIT 10"
  ).all();
}

async function queueView(env: Env) {
  const r = await getQueue(env);

  if (!r.results?.length) {
    return { text: "📭 Очередь пуста.", keyboard: mainMenu() };
  }

  const text =
    "📋 Очередь материалов:\n\n" +
    r.results
      .map((x: any) => `#${x.id} · ${x.category || "Без категории"} · ${x.status}\n${x.headline}`)
      .join("\n\n") +
    "\n\nНажми на статью ниже.";

  return { text, keyboard: queueKeyboard(r.results as any[]) };
}

async function analytics(env: Env) {
  const r = await env.DB.prepare(
    `SELECT a.id,a.headline,a.category,
      COALESCE(m.views,0) views,
      COALESCE(m.likes,0) likes,
      COALESCE(m.comments,0) comments,
      COALESCE(m.shares,0) shares
     FROM articles a
     LEFT JOIN metrics m ON m.article_id=a.id
     ORDER BY views DESC
     LIMIT 5`
  ).all();

  if (!r.results?.length) return "📊 Пока нет статистики.";

  return "📊 Топ материалов:\n\n" + r.results.map((x: any) => {
    const er = (
      (Number(x.likes || 0) + Number(x.comments || 0) * 2 + Number(x.shares || 0) * 3) /
      Math.max(Number(x.views || 0), 1) * 100
    ).toFixed(2);
    return `• ${x.views} просмотров · ER ${er}%\n${x.headline}`;
  }).join("\n\n");
}

async function strategy(env: Env) {
  const r = await env.DB.prepare("SELECT value FROM settings WHERE key='strategy'").first<any>();
  if (!r) return "🧠 Стратегия ещё не рассчитана. Она обновится после появления статистики.";

  try {
    const s = JSON.parse(r.value);
    const rows = Object.entries(s.categories || {}).sort(
      (a: any, b: any) => (b[1].weight || 0) - (a[1].weight || 0)
    );

    if (!rows.length) return "🧠 Пока недостаточно данных для стратегии.";

    return "🧠 Стратегия категорий:\n\n" + rows.map(
      ([k, v]: any) => `• ${k}: вес ${v.weight} · статей ${v.articles} · ср. просмотры ${v.avg_views}`
    ).join("\n");
  } catch {
    return "🧠 Стратегия повреждена — будет пересчитана следующим запуском.";
  }
}

async function quota(env: Env) {
  const day = new Date().toISOString().slice(0, 10);
  const row = await env.DB.prepare("SELECT requests FROM ai_usage WHERE day=?").bind(day).first<any>();
  const used = Number(row?.requests || 0);
  const limit = 50;

  return `📈 OpenRouter\n\nИспользовано сегодня: ${used}\nОсталось: ${Math.max(0, limit - used)}\nЛимит фабрики: ${limit}`;
}

async function getArticle(env: Env, id: number) {
  return env.DB.prepare(
    "SELECT id,headline,category,article_markdown,source_urls_json,fact_check_json,status,created_at,updated_at FROM articles WHERE id=?"
  ).bind(id).first<any>();
}

function articleCard(a: any) {
  return `📄 Материал #${a.id}\n\n${a.headline}\n\nКатегория: ${a.category || "Без категории"}\nСтатус: ${a.status}\nСоздан: ${a.created_at || "—"}`;
}

function splitText(text: string, max = 3900) {
  const result: string[] = [];
  let rest = text;

  while (rest.length > max) {
    let cut = rest.lastIndexOf("\n", max);
    if (cut < max * 0.6) cut = max;
    result.push(rest.slice(0, cut));
    rest = rest.slice(cut).replace(/^\n+/, "");
  }

  if (rest) result.push(rest);
  return result;
}

async function sendArticleText(env: Env, chat: string, a: any) {
  const full =
    `📝 ${a.headline}\n\n${a.article_markdown}\n\nСтатус: ${a.status}\n\nИсточники: ${a.source_urls_json}\n\nПроверка: ${a.fact_check_json}`;

  const parts = splitText(full);

  for (let i = 0; i < parts.length; i++) {
    await send(
      env,
      chat,
      parts[i],
      i === parts.length - 1 ? articleKeyboard(a.id, a.status) : undefined
    );
  }
}

async function statusText(env: Env) {
  const queued = await env.DB.prepare(
    "SELECT COUNT(*) n FROM articles WHERE status IN ('queued','needs_review')"
  ).first<any>();
  const approved = await env.DB.prepare(
    "SELECT COUNT(*) n FROM articles WHERE status='approved'"
  ).first<any>();
  const rejected = await env.DB.prepare(
    "SELECT COUNT(*) n FROM articles WHERE status='rejected'"
  ).first<any>();

  return `🟢 Dzen AI Factory Cloud\n\nНа проверке: ${Number(queued?.n || 0)}\nОдобрено: ${Number(approved?.n || 0)}\nОтклонено: ${Number(rejected?.n || 0)}\n\n${await quota(env)}`;
}

async function handleCallback(
  env: Env,
  chat: string,
  data: string,
  callbackId: string,
  messageId?: number
) {
  await tg(env, "answerCallbackQuery", { callback_query_id: callbackId });

  if (data === "menu") {
    const text = "🤖 Dzen AI Factory Cloud\nУправление фабрикой:";
    return messageId
      ? editMessage(env, chat, messageId, text, mainMenu())
      : send(env, chat, text, mainMenu());
  }

  if (data === "queue") {
    const q = await queueView(env);
    return messageId
      ? editMessage(env, chat, messageId, q.text, q.keyboard)
      : send(env, chat, q.text, q.keyboard);
  }

  if (data === "analytics") return send(env, chat, await analytics(env), mainMenu());
  if (data === "strategy") return send(env, chat, await strategy(env), mainMenu());
  if (data === "quota") return send(env, chat, await quota(env), mainMenu());
  if (data === "status") return send(env, chat, await statusText(env), mainMenu());

  if (data === "generate") {
    return send(
      env,
      chat,
      "⏰ Автогенерация настроена через GitHub Actions.\n\nРасписание: 06:00, 12:00 и 18:00 по Москве.\nКнопку ручного запуска подключим следующим этапом.",
      mainMenu()
    );
  }

  const articleMatch = /^article:(\d+)$/.exec(data);
  if (articleMatch) {
    const id = Number(articleMatch[1]);
    const a = await getArticle(env, id);
    if (!a) return send(env, chat, "Материал не найден.", mainMenu());

    return messageId
      ? editMessage(env, chat, messageId, articleCard(a), articleKeyboard(id, a.status))
      : send(env, chat, articleCard(a), articleKeyboard(id, a.status));
  }

  const approve = /^approve:(\d+)$/.exec(data);
  if (approve) {
    const id = Number(approve[1]);
    await env.DB.prepare(
      "UPDATE articles SET status='approved',updated_at=? WHERE id=?"
    ).bind(new Date().toISOString(), id).run();

    const a = await getArticle(env, id);
    if (!a) return send(env, chat, "Материал не найден.", mainMenu());

    const text = `✅ Материал #${id} одобрен.\n\n${a.headline}\n\nПубликация в Дзен остаётся отдельным официальным шагом.`;
    return messageId
      ? editMessage(env, chat, messageId, text, articleKeyboard(id, "approved"))
      : send(env, chat, text, articleKeyboard(id, "approved"));
  }

  const reject = /^reject:(\d+)$/.exec(data);
  if (reject) {
    const id = Number(reject[1]);
    await env.DB.prepare(
      "UPDATE articles SET status='rejected',updated_at=? WHERE id=?"
    ).bind(new Date().toISOString(), id).run();

    const a = await getArticle(env, id);
    if (!a) return send(env, chat, "Материал не найден.", mainMenu());

    const text = `❌ Материал #${id} отклонён.\n\n${a.headline}`;
    return messageId
      ? editMessage(env, chat, messageId, text, articleKeyboard(id, "rejected"))
      : send(env, chat, text, articleKeyboard(id, "rejected"));
  }

  const textMatch = /^text:(\d+)$/.exec(data);
  if (textMatch) {
    const id = Number(textMatch[1]);
    const a = await getArticle(env, id);
    if (!a) return send(env, chat, "Материал не найден.", mainMenu());
    return sendArticleText(env, chat, a);
  }
}

async function handleUpdate(env: Env, u: TgUpdate) {
  if (u.callback_query) {
    const cb = u.callback_query;
    const chat = String(cb.message?.chat?.id || "");
    const allowedChat = String(env.TELEGRAM_CHAT_ID || "").trim();
    if (allowedChat && chat !== allowedChat) return;

    return handleCallback(
      env,
      chat,
      String(cb.data || ""),
      cb.id,
      Number(cb.message?.message_id || 0)
    );
  }

  const m = u.message;
  if (!m) return;

  const chat = String(m?.chat?.id || "");
  const text = String(m?.text || "").trim();
  const allowedChat = String(env.TELEGRAM_CHAT_ID || "").trim();

  if (allowedChat && chat !== allowedChat) return;

  if (["/start", "/help", "/menu"].includes(text)) {
    return send(env, chat, "🤖 Dzen AI Factory Cloud\nУправление фабрикой:", mainMenu());
  }

  if (text === "/queue") {
    const q = await queueView(env);
    return send(env, chat, q.text, q.keyboard);
  }

  if (text === "/status") return send(env, chat, await statusText(env), mainMenu());
  if (text === "/analytics") return send(env, chat, await analytics(env), mainMenu());
  if (text === "/strategy") return send(env, chat, await strategy(env), mainMenu());
  if (text === "/limits") return send(env, chat, await quota(env), mainMenu());

  return send(env, chat, "Команда не распознана. Используй меню:", mainMenu());
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
        control_secret_configured: Boolean(env.CONTROL_SECRET),
        d1_configured: Boolean(env.DB),
      });
    }

    if (url.pathname === "/telegram/webhook" && req.method === "POST") {
      try {
        const u = await req.json<TgUpdate>();
        await handleUpdate(env, u);
        return json({ ok: true });
      } catch (error: any) {
        console.error(
          "Webhook handler error:",
          error?.stack || error?.message || String(error)
        );
        return json({ ok: false, error: "webhook_handler_error" }, 500);
      }
    }

    if (url.pathname === "/set-webhook" && req.method === "POST") {
      const secret = req.headers.get("x-control-secret");
      if (!env.CONTROL_SECRET || secret !== env.CONTROL_SECRET) {
        return json({ error: "unauthorized" }, 401);
      }

      const hook = `${url.origin}/telegram/webhook`;
      return json(
        await tg(env, "setWebhook", {
          url: hook,
          drop_pending_updates: true,
        })
      );
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
