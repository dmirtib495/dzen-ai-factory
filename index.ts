type Env = {
  DB: D1Database;
  TELEGRAM_BOT_TOKEN: string;
  TELEGRAM_CHAT_ID: string;
  CONTROL_SECRET: string;
  WORKFLOW_TRIGGER_TOKEN: string;
};

type TgUpdate = any;

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json; charset=utf-8" },
});

async function tg(env: Env, method: string, body: Record<string, unknown>) {
  if (!env.TELEGRAM_BOT_TOKEN) return { ok: false, description: "TELEGRAM_BOT_TOKEN is missing" };
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  let data: any;
  try { data = JSON.parse(text); } catch { data = { ok: false, description: text }; }
  if (!r.ok || !data?.ok) console.error(`Telegram API error ${method}:`, JSON.stringify(data));
  return data;
}

async function send(env: Env, chatId: string, text: string, keyboard?: unknown) {
  const body: Record<string, unknown> = { chat_id: chatId, text: text.slice(0, 4096), disable_web_page_preview: true };
  if (keyboard) body.reply_markup = keyboard;
  return tg(env, "sendMessage", body);
}

async function clearInlineKeyboard(env: Env, chatId: string, messageId?: number) {
  if (!messageId) return;
  await tg(env, "editMessageReplyMarkup", {
    chat_id: chatId,
    message_id: messageId,
    reply_markup: { inline_keyboard: [] },
  });
}

function mainMenu() {
  return { inline_keyboard: [
    [{ text: "🧭 Подобрать темы", callback_data: "generate" }, { text: "🔄 Статус", callback_data: "status" }],
    [{ text: "📋 Очередь", callback_data: "queue" }, { text: "📊 Аналитика", callback_data: "analytics" }],
    [{ text: "🧠 Стратегия", callback_data: "strategy" }, { text: "📈 Лимиты", callback_data: "quota" }],
  ] };
}

function articleKeyboard(id: number, status: string) {
  const rows: any[] = [[{ text: "📝 Читать статью", callback_data: `text:${id}` }]];
  if (status === "queued" || status === "needs_review") rows.push([
    { text: "✅ Одобрить", callback_data: `approve:${id}` },
    { text: "❌ Отклонить", callback_data: `reject:${id}` },
  ]);
  rows.push([{ text: "⬅️ К очереди", callback_data: "queue" }, { text: "🏠 Меню", callback_data: "menu" }]);
  return { inline_keyboard: rows };
}

async function queueView(env: Env) {
  const r = await env.DB.prepare(
    "SELECT id,headline,category,status,created_at FROM articles WHERE status IN ('queued','needs_review') ORDER BY id DESC LIMIT 10"
  ).all();
  if (!r.results?.length) return { text: "📭 Очередь пуста.", keyboard: mainMenu() };
  const rows = (r.results as any[]).map((x: any) => [{ text: `#${x.id} · ${String(x.headline).slice(0, 45)}`, callback_data: `article:${x.id}` }]);
  rows.push([{ text: "🏠 Главное меню", callback_data: "menu" }]);
  const text = "📋 Очередь материалов:\n\n" + (r.results as any[]).map((x: any) =>
    `#${x.id} · ${x.category || "Без категории"} · ${x.status}\n${x.headline}`
  ).join("\n\n");
  return { text, keyboard: { inline_keyboard: rows } };
}

async function analytics(env: Env) {
  const r = await env.DB.prepare(`SELECT a.id,a.headline,a.category,
    COALESCE(m.views,0) views,COALESCE(m.likes,0) likes,
    COALESCE(m.comments,0) comments,COALESCE(m.shares,0) shares
    FROM articles a LEFT JOIN metrics m ON m.article_id=a.id ORDER BY views DESC LIMIT 5`).all();
  if (!r.results?.length) return "📊 Пока нет статистики.";
  return "📊 Топ материалов:\n\n" + (r.results as any[]).map((x: any) => {
    const er = ((Number(x.likes||0)+Number(x.comments||0)*2+Number(x.shares||0)*3)/Math.max(Number(x.views||0),1)*100).toFixed(2);
    return `• ${x.views} просмотров · ER ${er}%\n${x.headline}`;
  }).join("\n\n");
}

async function strategy(env: Env) {
  const r = await env.DB.prepare("SELECT value FROM settings WHERE key='strategy'").first<any>();
  if (!r) return "🧠 Стратегия ещё не рассчитана.";
  try {
    const s = JSON.parse(r.value);
    const rows = Object.entries(s.categories || {}).sort((a:any,b:any)=>(b[1].weight||0)-(a[1].weight||0));
    if (!rows.length) return "🧠 Пока недостаточно данных для стратегии.";
    return "🧠 Стратегия категорий:\n\n" + rows.map(([k,v]:any)=>`• ${k}: вес ${v.weight} · статей ${v.articles} · ср. просмотры ${v.avg_views}`).join("\n");
  } catch { return "🧠 Стратегия повреждена — будет пересчитана."; }
}

async function quota(env: Env) {
  const day = new Date().toISOString().slice(0, 10);
  const ai = await env.DB.prepare("SELECT requests FROM ai_usage WHERE day=?").bind(day).first<any>();
  const img = await env.DB.prepare("SELECT used FROM resource_usage WHERE day=? AND resource='workers_ai_neurons'").bind(day).first<any>();
  const aiUsed = Number(ai?.requests || 0);
  const neurons = Number(img?.used || 0);
  const neuronBudget = 172.8 * 34;
  const generations = Math.floor(neurons / 172.8 + 1e-9);
  return `📈 Дневные лимиты\n\nOpenRouter: ${aiUsed}/50 · осталось ${Math.max(0,50-aiUsed)}\n` +
    `Workers AI: ${neurons.toFixed(1)}/${neuronBudget.toFixed(1)} neurons · ${generations}/34 генераций зарезервировано`;
}

async function statusText(env: Env) {
  const queued = await env.DB.prepare("SELECT COUNT(*) n FROM articles WHERE status IN ('queued','needs_review')").first<any>();
  const images = await env.DB.prepare("SELECT COUNT(*) n FROM image_batches WHERE status='pending_review'").first<any>();
  const topics = await env.DB.prepare("SELECT COUNT(*) n FROM topic_proposal_groups WHERE status='pending'").first<any>();
  return `🟢 Dzen AI Factory Cloud\n\nТем ждут твоего выбора: ${Number(topics?.n||0)}\n` +
    `Статей в очереди: ${Number(queued?.n||0)}\nНаборов изображений ждут решения: ${Number(images?.n||0)}\n\n${await quota(env)}`;
}

async function getArticle(env: Env, id: number) {
  return env.DB.prepare("SELECT id,headline,category,article_markdown,source_urls_json,fact_check_json,status,created_at,updated_at FROM articles WHERE id=?").bind(id).first<any>();
}

function splitText(text: string, max = 3900) {
  const result: string[] = []; let rest = text;
  while (rest.length > max) {
    let cut = rest.lastIndexOf("\n", max); if (cut < max * 0.6) cut = max;
    result.push(rest.slice(0, cut)); rest = rest.slice(cut).replace(/^\n+/, "");
  }
  if (rest) result.push(rest); return result;
}

async function sendArticleText(env: Env, chat: string, a: any) {
  const parts = splitText(`📝 ${a.headline}\n\n${a.article_markdown}\n\nСтатус: ${a.status}\n\nИсточники: ${a.source_urls_json}\n\nПроверка: ${a.fact_check_json}`);
  for (let i=0;i<parts.length;i++) await send(env,chat,parts[i],i===parts.length-1?articleKeyboard(a.id,a.status):undefined);
}

async function dispatchWorkflow(env: Env, workflow: string, inputs: Record<string,string>) {
  if (!env.WORKFLOW_TRIGGER_TOKEN) return { ok:false,status:0,message:"WORKFLOW_TRIGGER_TOKEN не настроен" };
  const r = await fetch(`https://api.github.com/repos/dmirtib495/dzen-ai-factory/actions/workflows/${workflow}/dispatches`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${env.WORKFLOW_TRIGGER_TOKEN}`,
      "Accept": "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dzen-auto-control-worker",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref:"main", inputs }),
  });
  if (r.status === 204) return { ok:true,status:204,message:"workflow_dispatch accepted" };
  const body = await r.text();
  console.error("GitHub workflow dispatch failed", workflow, r.status, body.slice(0,500));
  return { ok:false,status:r.status,message:body.slice(0,500) };
}

async function handleTopicPick(env: Env, chat: string, proposalId: number, messageId?: number) {
  const p = await env.DB.prepare(`SELECT p.id,p.group_id,p.position,p.title,p.status,g.status AS group_status
    FROM topic_proposals p JOIN topic_proposal_groups g ON g.id=p.group_id WHERE p.id=?`).bind(proposalId).first<any>();
  if (!p) return send(env,chat,`Тема #${proposalId} не найдена.`,mainMenu());
  if (p.group_status !== "pending") {
    await clearInlineKeyboard(env,chat,messageId);
    return send(env,chat,"Для этого набора тем решение уже принято.",mainMenu());
  }

  const now = new Date().toISOString();
  const claim = await env.DB.prepare(
    "UPDATE topic_proposal_groups SET status='selected',selected_proposal_id=?,updated_at=? WHERE id=? AND status='pending'"
  ).bind(proposalId,now,p.group_id).run();
  if (!claim.meta?.changes) return send(env,chat,"Тема уже была выбрана другим нажатием.",mainMenu());

  await env.DB.prepare("UPDATE topic_proposals SET status=CASE WHEN id=? THEN 'approved' ELSE 'rejected' END,updated_at=? WHERE group_id=?")
    .bind(proposalId,now,p.group_id).run();
  await clearInlineKeyboard(env,chat,messageId);

  const dispatched = await dispatchWorkflow(env,"generate-approved-topic.yml",{proposal_id:String(proposalId)});
  if (!dispatched.ok) {
    await env.DB.prepare("UPDATE topic_proposal_groups SET status='pending',selected_proposal_id=NULL,updated_at=? WHERE id=?").bind(new Date().toISOString(),p.group_id).run();
    await env.DB.prepare("UPDATE topic_proposals SET status='pending',updated_at=? WHERE group_id=?").bind(new Date().toISOString(),p.group_id).run();
    return send(env,chat,`❌ Тема выбрана, но запуск статьи не стартовал. GitHub API: ${dispatched.status}. Запроси темы ещё раз.`,mainMenu());
  }
  return send(env,chat,`✅ Тема утверждена:\n\n${p.title}\n\nТеперь фабрика начинает писать статью. Другие варианты из этого набора отклонены.`,mainMenu());
}

async function handleTopicRefresh(env: Env, chat: string, groupId: string, messageId?: number) {
  const now = new Date().toISOString();
  const update = await env.DB.prepare("UPDATE topic_proposal_groups SET status='discarded',updated_at=? WHERE id=? AND status='pending'").bind(now,groupId).run();
  if (!update.meta?.changes) return send(env,chat,"Этот набор тем уже обработан.",mainMenu());
  await env.DB.prepare("UPDATE topic_proposals SET status='rejected',updated_at=? WHERE group_id=? AND status='pending'").bind(now,groupId).run();
  await clearInlineKeyboard(env,chat,messageId);
  const r = await dispatchWorkflow(env,"dzen-cloud.yml",{trigger_source:"telegram-refresh"});
  return send(env,chat,r.ok?"🔄 Подбираю новый набор тем. Статья пока не создаётся.":`❌ Не удалось запросить новые темы. GitHub API: ${r.status}.`,mainMenu());
}

async function handleImageSetDecision(env: Env, chat: string, batchId: number, action: "ok"|"regen", messageId?: number) {
  const batch = await env.DB.prepare("SELECT id,article_id,attempt,status,source_run_id,artifact_name FROM image_batches WHERE id=?").bind(batchId).first<any>();
  if (!batch) return send(env,chat,`Набор #${batchId} не найден.`,mainMenu());
  if (batch.status !== "pending_review") {
    await clearInlineKeyboard(env,chat,messageId);
    return send(env,chat,`Набор #${batchId} уже обработан: ${batch.status}.`,mainMenu());
  }
  const nextStatus = action === "ok" ? "approved" : "rejected";
  const update = await env.DB.prepare("UPDATE image_batches SET status=?,updated_at=? WHERE id=? AND status='pending_review'")
    .bind(nextStatus,new Date().toISOString(),batchId).run();
  if (!update.meta?.changes) return send(env,chat,"Решение уже было принято другим запросом.",mainMenu());
  await clearInlineKeyboard(env,chat,messageId);

  if (action === "regen") {
    const dispatched = await dispatchWorkflow(env,"image-batch.yml",{article_id:String(batch.article_id)});
    if (!dispatched.ok) {
      await env.DB.prepare("UPDATE image_batches SET status='pending_review',updated_at=? WHERE id=?").bind(new Date().toISOString(),batchId).run();
      return send(env,chat,`❌ Не удалось запустить новый набор. GitHub API: ${dispatched.status}.`,mainMenu());
    }
    return send(env,chat,`♻️ Набор #${batchId} отклонён. Генерирую новый набор для статьи #${batch.article_id}.`,mainMenu());
  }

  const dispatched = await dispatchWorkflow(env,"finalize-image-package.yml",{
    article_id:String(batch.article_id), batch_id:String(batch.id),
    source_run_id:String(batch.source_run_id), artifact_name:String(batch.artifact_name),
  });
  if (!dispatched.ok) {
    await env.DB.prepare("UPDATE image_batches SET status='pending_review',updated_at=? WHERE id=?").bind(new Date().toISOString(),batchId).run();
    return send(env,chat,`❌ Набор принят, но финализация не стартовала. GitHub API: ${dispatched.status}.`,mainMenu());
  }
  return send(env,chat,`✅ Набор #${batchId} принят. Запускаю DOCX/ZIP для статьи #${batch.article_id}.`,mainMenu());
}

async function handleCallback(env: Env, chat: string, data: string, callbackId: string, messageId?: number) {
  await tg(env,"answerCallbackQuery",{callback_query_id:callbackId});

  const topicPick = /^topic_pick:(\d+)$/.exec(data);
  if (topicPick) return handleTopicPick(env,chat,Number(topicPick[1]),messageId);
  const topicRefresh = /^topic_refresh:([a-z0-9]+)$/.exec(data);
  if (topicRefresh) return handleTopicRefresh(env,chat,topicRefresh[1],messageId);
  const okSet = /^imageset_ok:(\d+)$/.exec(data);
  if (okSet) return handleImageSetDecision(env,chat,Number(okSet[1]),"ok",messageId);
  const regenSet = /^imageset_regen:(\d+)$/.exec(data);
  if (regenSet) return handleImageSetDecision(env,chat,Number(regenSet[1]),"regen",messageId);

  if (data === "menu") return send(env,chat,"🤖 Dzen AI Factory Cloud\nУправление фабрикой:",mainMenu());
  if (data === "queue") { const q=await queueView(env); return send(env,chat,q.text,q.keyboard); }
  if (data === "analytics") return send(env,chat,await analytics(env),mainMenu());
  if (data === "strategy") return send(env,chat,await strategy(env),mainMenu());
  if (data === "quota") return send(env,chat,await quota(env),mainMenu());
  if (data === "status") return send(env,chat,await statusText(env),mainMenu());
  if (data === "generate") {
    await send(env,chat,"🧭 Подбираю свежие темы. Статью начну только после твоего выбора.");
    const r=await dispatchWorkflow(env,"dzen-cloud.yml",{trigger_source:"telegram-worker"});
    return send(env,chat,r.ok?"✅ Поиск тем запущен.":`❌ Запуск не удался. GitHub API: ${r.status}.`,mainMenu());
  }

  const articleMatch=/^article:(\d+)$/.exec(data);
  if (articleMatch) {
    const a=await getArticle(env,Number(articleMatch[1]));
    if (!a) return send(env,chat,"Материал не найден.",mainMenu());
    return send(env,chat,`📄 Материал #${a.id}\n\n${a.headline}\n\nКатегория: ${a.category || "Без категории"}\nСтатус: ${a.status}`,articleKeyboard(a.id,a.status));
  }
  const approve=/^approve:(\d+)$/.exec(data);
  if (approve) {
    const id=Number(approve[1]);
    await env.DB.prepare("UPDATE articles SET status='approved',updated_at=? WHERE id=?").bind(new Date().toISOString(),id).run();
    const a=await getArticle(env,id); return send(env,chat,a?`✅ Материал #${id} одобрен.\n\n${a.headline}`:"Материал не найден.",mainMenu());
  }
  const reject=/^reject:(\d+)$/.exec(data);
  if (reject) {
    const id=Number(reject[1]);
    await env.DB.prepare("UPDATE articles SET status='rejected',updated_at=? WHERE id=?").bind(new Date().toISOString(),id).run();
    const a=await getArticle(env,id); return send(env,chat,a?`❌ Материал #${id} отклонён.\n\n${a.headline}`:"Материал не найден.",mainMenu());
  }
  const textMatch=/^text:(\d+)$/.exec(data);
  if (textMatch) {
    const a=await getArticle(env,Number(textMatch[1]));
    if (!a) return send(env,chat,"Материал не найден.",mainMenu());
    return sendArticleText(env,chat,a);
  }
}

async function handleUpdate(env: Env, u: TgUpdate) {
  if (u.callback_query) {
    const cb=u.callback_query; const chat=String(cb.message?.chat?.id||"");
    const allowed=String(env.TELEGRAM_CHAT_ID||"").trim(); if (allowed && chat!==allowed) return;
    return handleCallback(env,chat,String(cb.data||""),cb.id,Number(cb.message?.message_id||0));
  }
  const m=u.message; if (!m) return;
  const chat=String(m?.chat?.id||""); const text=String(m?.text||"").trim();
  const allowed=String(env.TELEGRAM_CHAT_ID||"").trim(); if (allowed && chat!==allowed) return;
  if (["/start","/help","/menu"].includes(text)) return send(env,chat,"🤖 Dzen AI Factory Cloud\nУправление фабрикой:",mainMenu());
  if (text==="/queue") { const q=await queueView(env); return send(env,chat,q.text,q.keyboard); }
  if (text==="/status") return send(env,chat,await statusText(env),mainMenu());
  if (text==="/analytics") return send(env,chat,await analytics(env),mainMenu());
  if (text==="/strategy") return send(env,chat,await strategy(env),mainMenu());
  if (text==="/limits") return send(env,chat,await quota(env),mainMenu());
  if (text==="/generate") {
    const r=await dispatchWorkflow(env,"dzen-cloud.yml",{trigger_source:"telegram-worker"});
    return send(env,chat,r.ok?"🧭 Подбор тем запущен. Статья начнётся только после твоего выбора.":`❌ Запуск не удался. GitHub API: ${r.status}.`,mainMenu());
  }
  return send(env,chat,"Команда не распознана. Используй меню:",mainMenu());
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url=new URL(req.url);
    if (url.pathname==="/health") return json({
      ok:true,service:"dzen-auto-control",
      telegram_token_configured:Boolean(env.TELEGRAM_BOT_TOKEN),
      telegram_chat_configured:Boolean(env.TELEGRAM_CHAT_ID),
      control_secret_configured:Boolean(env.CONTROL_SECRET),
      workflow_trigger_configured:Boolean(env.WORKFLOW_TRIGGER_TOKEN),
      d1_configured:Boolean(env.DB), image_set_approval:true, topic_approval:true,
    });
    if (url.pathname==="/telegram/webhook" && req.method==="POST") {
      try { const u=await req.json<TgUpdate>(); await handleUpdate(env,u); return json({ok:true}); }
      catch(error:any) { console.error("Webhook handler error:",error?.stack||error?.message||String(error)); return json({ok:false,error:"webhook_handler_error"},500); }
    }
    if (url.pathname==="/set-webhook" && req.method==="POST") {
      const secret=req.headers.get("x-control-secret");
      if (!env.CONTROL_SECRET || secret!==env.CONTROL_SECRET) return json({error:"unauthorized"},401);
      return json(await tg(env,"setWebhook",{url:`${url.origin}/telegram/webhook`,drop_pending_updates:true}));
    }
    return json({ok:false,error:"not_found"},404);
  },
};
