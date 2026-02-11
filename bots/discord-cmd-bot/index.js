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

client.once("ready", () => {
  console.log(`✅ MZ Bot online as ${client.user.tag}`);
});

client.on("messageCreate", async (msg) => {
  console.log("Message:", {
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
    const text = msg.content.replace(/<@!?(\d+)>/g, "").trim();
    const parts = text.split(/\s+/).filter(Boolean);

    // Se mencionou e não escreveu nada
    if (parts.length === 0) {
      await msg.reply("Uso: `@MZ posts create <project>` ou `@MZ email last <project>`");
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

    const help = "Comandos: `posts create <project>` | `email last <project>`";

    if (!allowedDomains.has(domain)) {
      await msg.reply(`❌ Domínio não reconhecido. ${help}`);
      return;
    }

    if (!action || !allowedActions[domain].has(action)) {
      await msg.reply(`❌ Ação não reconhecida para ${domain}. ${help}`);
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
      email: { last: "email_check" }
    };
    const taskType = typeMap?.[domain]?.[action];
    if (!taskType) {
      await msg.reply(`❌ Ação não reconhecida para ${domain}. ${help}`);
      return;
    }

    const name = `${domain} ${action} ${project}`;

    await msg.reply(`⏳ Task criada no Notion: \`${name}\``);

    try {
      const payload = {
        parent: { database_id: notionDbId },
        properties: {
          Name: { title: [{ text: { content: name } }] },
          Status: { select: { name: "queued" } },
          Type: { select: { name: taskType } },
          Project: { select: { name: project } },
          RequestedBy: { select: { name: "discord" } },
        }
      };

      const res = await fetch("https://api.notion.com/v1/pages", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${notionToken}`,
          "Content-Type": "application/json",
          "Notion-Version": "2022-06-28",
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errText = await res.text();
        await msg.reply(`❌ Falha ao criar task no Notion. ${errText}`);
        return;
      }

      await msg.reply(`✅ Task enfileirada: \`${taskType}\` (${project})`);
    } catch (err) {
      await msg.reply("❌ Erro ao criar task no Notion.");
      console.error(err);
    }
  } catch (e) {
    // Evita crash silencioso
    try {
      await msg.reply("❌ Erro interno ao processar o comando.");
    } catch (_) {}
    console.error("Handler error:", e);
  }
});


client.login(TOKEN);
