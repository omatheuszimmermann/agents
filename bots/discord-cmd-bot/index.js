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

const REPO_ROOT = path.resolve(__dirname, "..", "..");
const POSTS_PROJECTS_DIR = path.join(REPO_ROOT, "agents", "social-posts", "projects");
const EMAIL_PROJECTS_DIR = path.join(REPO_ROOT, "agents", "email-triage", "projects");

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

function iconForTaskType(taskType) {
  const map = {
    email_check: "📧",
    email_tasks_create: "🧾",
    posts_create: "📝",
    content_refresh: "📚",
    lesson_send: "🎓",
    lesson_correct: "✅",
  };
  return map[taskType] || "⚙️";
}

function projectExists(domain, project) {
  if (!project) return false;
  if (domain === "posts") {
    const projectFile = path.join(
      POSTS_PROJECTS_DIR,
      project,
      "project.md"
    );
    return fs.existsSync(projectFile);
  }
  if (domain === "email") {
    const envFile = path.join(
      EMAIL_PROJECTS_DIR,
      project,
      ".env"
    );
    return fs.existsSync(envFile);
  }
  return false;
}

function listDirectories(baseDir) {
  try {
    return fs
      .readdirSync(baseDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort((a, b) => a.localeCompare(b));
  } catch (err) {
    logError(`Failed to list directories in ${baseDir}:`, err);
    return [];
  }
}

function formatProjectsMessage() {
  const postsProjects = listDirectories(POSTS_PROJECTS_DIR);
  const emailProjects = listDirectories(EMAIL_PROJECTS_DIR);

  const postsLine = postsProjects.length
    ? postsProjects.map((p) => `\`${p}\``).join(", ")
    : "(nenhum)";
  const emailLine = emailProjects.length
    ? emailProjects.map((p) => `\`${p}\``).join(", ")
    : "(nenhum)";

  return `Projetos disponíveis:\n- posts: ${postsLine}\n- email: ${emailLine}`;
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

    const help = [
      "Comandos válidos:",
      "- `posts create <project>`",
      "- `email last <project>`",
      "- `languages refresh`",
      "- `languages send <student_id> [lesson_type|random] [topic]`",
      "- `help commands`",
      "- `help projects`",
    ].join("\n");

    if (parts.length === 0) {
      await msg.reply(`❌ Comando incompleto. ${help}`);
      return;
    }

    const domain = (parts[0] || "").toLowerCase();
    const action = (parts[1] || "").toLowerCase();
    const project = (parts[2] || "").toLowerCase();

    if (domain === "help") {
      if (action === "commands") {
        await msg.reply(help);
        return;
      }
      if (action === "projects") {
        await msg.reply(formatProjectsMessage());
        return;
      }
      await msg.reply(`❌ Ajuda inválida. ${help}`);
      return;
    }

    const allowedDomains = new Set(["posts", "email", "languages"]);
    const allowedActions = {
      posts: new Set(["create"]),
      email: new Set(["last"]),
      languages: new Set(["refresh", "send"]),
    };

    if (!allowedDomains.has(domain)) {
      await msg.reply(`❌ Domínio inválido. ${help}`);
      return;
    }

    if (!action || !allowedActions[domain].has(action)) {
      await msg.reply(`❌ Ação inválida para ${domain}. ${help}`);
      return;
    }

    if (domain !== "languages" && !project) {
      await msg.reply(`❌ Falta o projeto. ${help}`);
      return;
    }

    if (domain !== "languages") {
      if (!projectExists(domain, project)) {
        const errorMsg = `❌ Projeto inexistente para ${domain}: \`${project}\`. Verifique a pasta do projeto.`;
        await msg.reply(errorMsg);
        await sendErrorToDiscord(`[bot] Invalid project: domain=${domain} project=${project}`);
        return;
      }
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
      languages: { refresh: "content_refresh", send: "lesson_send" },
    };
    const taskType = typeMap?.[domain]?.[action];
    if (!taskType) {
      await msg.reply(`❌ Ação inválida para ${domain}. ${help}`);
      return;
    }

    let notionProject = project;
    let payloadText = "";
      if (domain === "languages") {
        notionProject = "languages";
        if (action === "send") {
          const studentId = (parts[2] || "").toLowerCase();
          const lessonType = (parts[3] || "").toLowerCase();
          const topic = (parts[4] || "").toLowerCase();
          if (!studentId) {
            await msg.reply(`❌ Falta o student_id. ${help}`);
            return;
          }
          const payloadObj = { student_id: studentId };
          if (lessonType && lessonType !== "random") {
            payloadObj.lesson_type = lessonType;
          }
          if (topic) payloadObj.topic = topic;
          payloadText = JSON.stringify(payloadObj);
          if (lessonType && lessonType === "random") {
            payloadText = JSON.stringify(payloadObj);
          } else {
            payloadText = JSON.stringify(payloadObj);
          }
        }
      }

    const name = `${domain} ${action} ${notionProject}`;
    const icon = iconForTaskType(taskType);

    const payload = {
      parent: { database_id: notionDbId },
      icon: { emoji: icon },
      properties: {
        Name: { title: [{ text: { content: name } }] },
        Status: { select: { name: "queued" } },
        Type: { select: { name: taskType } },
        Project: { select: { name: notionProject } },
        RequestedBy: { select: { name: "discord" } },
      },
    };
    if (payloadText) {
      payload.properties.Payload = { rich_text: [{ text: { content: payloadText } }] };
    }

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
