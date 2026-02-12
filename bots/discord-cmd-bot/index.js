const fs = require("fs");
const path = require("path");
const { Client, GatewayIntentBits } = require("discord.js");

function loadEnv(envPath) {
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf8").split(/\r?\n/);
  for (const line of lines) {
    const s = line.trim();
    if (!s || s.startsWith("#") || !s.includes("=")) continue;
    const [k, ...rest] = s.split("=");
    if (!process.env[k]) process.env[k] = rest.join("=").trim();
  }
}

const ENV_PATH = path.join(__dirname, ".env");
loadEnv(ENV_PATH);
loadEnv(path.resolve(__dirname, "..", "..", "integrations", "notion", ".env"));

const TOKEN = process.env.DISCORD_TOKEN;

if (!TOKEN) {
  console.error("Missing DISCORD_TOKEN in .env");
  process.exit(1);
}

const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.MessageContent,
  ],
});

function ts() {
  return new Date().toISOString();
}

function log(...args) {
  console.log(`[${ts()}]`, ...args);
}

function logError(...args) {
  console.error(`[${ts()}]`, ...args);
}

function formatDayMonth(date = new Date()) {
  const dd = String(date.getDate()).padStart(2, "0");
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  return `${dd}/${mm}`;
}

function iconForTaskType(taskType) {
  const map = {
    email_check: "📧",
    email_tasks_create: "🧾",
    posts_create: "📝",
  };
  return map[taskType] || "⚙️";
}

function getUniqueIdText(page, propName = "ID") {
  const prop = page?.properties?.[propName];
  const unique = prop?.unique_id;
  if (!unique || unique.number == null) return "";
  if (unique.prefix) return `${unique.prefix}-${unique.number}`;
  return String(unique.number);
}

async function sendErrorToDiscord(message) {
  const channelId = process.env.DISCORD_LOG_CHANNEL_ID;
  if (!channelId) return;
  try {
    const channel = await client.channels.fetch(channelId);
    if (!channel || !channel.isTextBased()) return;
    await channel.send(message);
  } catch (err) {
    logError("Failed to send error to log channel:", err);
  }
}

function handleReady() {
  log(`✅ MZ Bot online as ${client.user.tag}`);
}

client.once("clientReady", handleReady);

client.on("messageCreate", async (msg) => {
  log("Message:", {
    channelId: msg.channelId,
    content: msg.content,
  });

  try {
    if (msg.author.bot) return;

    const botId = client.user.id;
    const mentionPattern = new RegExp(`<@!?${botId}>`);
    const mentioned =
      msg.mentions?.users?.has(botId) ||
      mentionPattern.test(msg.content);

    // Só processa quando for mencionado
    if (!mentioned) return;

    // Remove menções do texto e normaliza
    const text = msg.content.replace(/<@!?\d+>/g, "").trim();
    const parts = text.split(/\s+/).filter(Boolean);

    const help = "Comandos válidos: `posts create <project>` | `email last <project>`";

    if (parts.length === 0) {
      await msg.reply(`❌ Comando incompleto. ${help}`);
      return;
    }

    const domain = (parts[0] || "").toLowerCase();
    const action = (parts[1] || "").toLowerCase();
    const project = (parts[2] || "").toLowerCase();

    const allowedDomains = new Set(["posts", "email"]);
    const allowedActions = {
      posts: new Set(["create"]),
      email: new Set(["last"]),
    };

    if (!allowedDomains.has(domain)) {
      await msg.reply(`❌ Domínio inválido. ${help}`);
      return;
    }

    if (!action || !allowedActions[domain].has(action)) {
      await msg.reply(`❌ Ação inválida para ${domain}. ${help}`);
      return;
    }

    if (!project) {
      await msg.reply(`❌ Falta o projeto. ${help}`);
      return;
    }

    const notionToken = process.env.NOTION_API_KEY;
    const notionDbId = process.env.NOTION_DB_ID;
    if (!notionToken || !notionDbId) {
      await msg.reply("❌ Notion não configurado (NOTION_API_KEY / NOTION_DB_ID).");
      return;
    }

    const typeMap = {
      posts: { create: "posts_create" },
      email: { last: "email_check" },
    };
    const taskType = typeMap?.[domain]?.[action];
    if (!taskType) {
      await msg.reply(`❌ Ação inválida para ${domain}. ${help}`);
      return;
    }

    const name = `${domain} ${action} ${project}`;
    const icon = iconForTaskType(taskType);

    const payload = {
      parent: { database_id: notionDbId },
      icon: { emoji: icon },
      properties: {
        Name: { title: [{ text: { content: name } }] },
        Status: { select: { name: "queued" } },
        Type: { select: { name: taskType } },
        Project: { select: { name: project } },
        RequestedBy: { select: { name: "discord" } },
      },
    };

    try {
      const res = await fetch("https://api.notion.com/v1/pages", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${notionToken}`,
          "Content-Type": "application/json",
          "Notion-Version": "2022-06-28",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errText = await res.text();
        await msg.reply(`❌ Falha ao criar task no Notion. ${errText}`);
        await sendErrorToDiscord(`[bot] Notion create failed: ${errText}`);
        return;
      }

      const page = await res.json();
      const ticket = getUniqueIdText(page, "ID");
      if (ticket) {
        const event = `${taskType} ${project}`;
        const title = `${icon} #${ticket} ${formatDayMonth()} - ${event}`;
        try {
          await fetch(`https://api.notion.com/v1/pages/${page.id}`, {
            method: "PATCH",
            headers: {
              Authorization: `Bearer ${notionToken}`,
              "Content-Type": "application/json",
              "Notion-Version": "2022-06-28",
            },
            body: JSON.stringify({
              properties: {
                Name: { title: [{ text: { content: title } }] },
              },
            }),
          });
        } catch (err) {
          await sendErrorToDiscord(`[bot] Notion title update failed: ${err?.message || err}`);
        }
      }

      await msg.reply(`✅ Task criada no Notion: \`${taskType}\` (${project})`);
    } catch (err) {
      await msg.reply("❌ Erro ao criar task no Notion.");
      await sendErrorToDiscord(`[bot] Notion error: ${err?.message || err}`);
      logError(err);
    }
  } catch (e) {
    try {
      await msg.reply("❌ Erro interno ao processar o comando.");
    } catch (_) {}
    await sendErrorToDiscord(`[bot] Handler error: ${e?.message || e}`);
    logError("Handler error:", e);
  }
});

client.login(TOKEN);
