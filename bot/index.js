import minecraftData from "minecraft-data";
import mineflayer from "mineflayer";
import pathfinderPkg from "mineflayer-pathfinder";

const { pathfinder, Movements, goals } = pathfinderPkg;

const HOST = process.env.MC_HOST || "127.0.0.1";
const PORT = Number(process.env.MC_PORT || 25565);
const USERNAME = process.env.MC_USERNAME || "LuoBot";
const VERSION = process.env.MC_VERSION || "1.20.4";

const bot = mineflayer.createBot({
  host: HOST,
  port: PORT,
  username: USERNAME,
  auth: "offline",
  version: VERSION,
});

bot.loadPlugin(pathfinder);

function say(text) {
  bot.chat(text);
}

function movements() {
  const data = minecraftData(bot.version);
  return new Movements(bot, data);
}

function follow(username) {
  const player = bot.players[username];
  if (!player || !player.entity) {
    say(`看不到 ${username}`);
    return;
  }
  bot.pathfinder.setMovements(movements());
  bot.pathfinder.setGoal(new goals.GoalFollow(player.entity, 2), true);
  say(`跟着 ${username}`);
}

bot.once("spawn", () => {
  const p = bot.entity.position;
  console.log(`[bot] spawned at ${p.x} ${p.y} ${p.z}`);
  say("我进来了");
});

bot.on("error", (err) => console.error("[bot] error", err));
bot.on("kicked", (reason) => console.error("[bot] kicked", reason));
bot.on("end", (reason) => console.log("[bot] end", reason));

bot.on("chat", (username, message) => {
  if (username === bot.username) return;
  const [cmd, ...args] = message.trim().split(/\s+/);
  if (cmd === "!follow") {
    follow(args[0] || username);
  } else if (cmd === "!stop") {
    bot.pathfinder.setGoal(null);
    say("停了");
  } else if (cmd === "!goto") {
    const [x, y, z] = args.map(Number);
    if ([x, y, z].some(Number.isNaN)) {
      say("用法：!goto x y z");
      return;
    }
    bot.pathfinder.setMovements(movements());
    bot.pathfinder.setGoal(new goals.GoalBlock(x, y, z));
    say(`去 ${x} ${y} ${z}`);
  } else if (cmd === "!state") {
    const p = bot.entity.position;
    say(`我在 ${p.x.toFixed(1)} ${p.y.toFixed(1)} ${p.z.toFixed(1)}，血量 ${bot.health}`);
  } else if (cmd === "!say") {
    say(args.join(" "));
  }
});
