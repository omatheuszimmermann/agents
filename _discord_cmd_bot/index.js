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
      await msg.reply("Uso: `@MZ create <project>`");
      return;
    }

    const cmd = (parts[0] || "").toLowerCase();

    // Lista de comandos suportados
    const help = "Comandos: `create <project>`";

    if (cmd !== "create") {
      await msg.reply(`❌ Comando não reconhecido. ${help}`);
      return;
    }

    // Validação do parâmetro
    const project = (parts[1] || "").toLowerCase();
    if (!project) {
      await msg.reply("❌ Falta o projeto. Uso: `@MZ create <project>`");
      return;
    }

    // Mapeamento project -> job id
    const jobId = `socialmedia_${project}`;

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
