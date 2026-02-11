const fs = require("fs");
const path = require("path");
const { Client, GatewayIntentBits } = require("discord.js");
const { execFile } = require("child_process");

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

function runForcedJob(jobId, cb) {
  const py = "/usr/bin/python3";
  const runner = path.resolve(__dirname, "..", "..", "runner", "run_jobs.py");
  execFile(py, [runner, "--force", jobId], { timeout: 15 * 60 * 1000 }, (err, stdout, stderr) => {
    cb(err, stdout, stderr);
  });
}

client.on("clientReady", () => {
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

    const jobId = `${domain}_${project}_${action}`;

    await msg.reply(`⏳ Executando agora: \`${jobId}\``);

    runForcedJob(jobId, async (err, stdout, stderr) => {
      if (err) {
        await msg.reply(`❌ Falhou ao executar \`${jobId}\`. Verifique os logs no servidor.`);
        return;
      }
      await msg.reply(`✅ Concluído: \`${jobId}\``);
    });
  } catch (e) {
    // Evita crash silencioso
    try {
      await msg.reply("❌ Erro interno ao processar o comando.");
    } catch (_) {}
    console.error("Handler error:", e);
  }
});


client.login(TOKEN);
