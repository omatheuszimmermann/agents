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
  const runner = "/Users/matheuszimmermannai/Documents/agents/_runner/run_jobs.py";
  execFile(py, [runner, "--force", jobId], { timeout: 15 * 60 * 1000 }, (err, stdout, stderr) => {
    cb(err, stdout, stderr);
  });
}

client.on("clientReady", () => {
  console.log(`✅ MZ Bot online as ${client.user.tag}`);
});

client.on("messageCreate", async (msg) => {
  console.log("MSG:", {
    author: msg.author.username,
    content: msg.content,
    channelId: msg.channelId,
    mentionsMe: msg.mentions.users.has(client.user.id),
    }
  )
  if (msg.author.bot) return;

  // só responde se for mencionado
  const botId = client.user.id;

  const mentionPattern = new RegExp(`<@!?${botId}>`);
  const mentioned = msg.mentions?.users?.has(botId) || mentionPattern.test(msg.content);
  if (!mentioned) return;

  const text = msg.content.replace(/<@!?(\d+)>/g, "").trim();
  const parts = text.split(/\s+/).filter(Boolean);

  // formato: @MZ create secureapix
  const cmd = (parts[0] || "").toLowerCase();
  const project = (parts[1] || "").toLowerCase();

  if (!cmd) {
    await msg.reply("Uso: @MZ create <project>");
    return;
  }

  if (cmd === "create") {
    if (!project) {
      await msg.reply("Uso: @MZ create <project>");
      return;
    }

    // mapeamento project -> job id (simples e explícito)
    const jobId = `socialmedia_${project}`;

    await msg.reply(`⏳ Rodando agora: ${jobId}`);

    runForcedJob(jobId, async (err) => {
      if (err) {
        await msg.reply(`❌ Falhou ao executar ${jobId}. Veja logs no servidor.`);
        return;
      }
      await msg.reply(`✅ Executado: ${jobId}`);
    });

    return;
  }

  await msg.reply("Comandos: create");
});

client.login(TOKEN);
