import minecraftData from "minecraft-data";
import mineflayer from "mineflayer";
import pathfinderPkg from "mineflayer-pathfinder";
import { WebSocketServer } from "ws";

const { pathfinder, Movements, goals } = pathfinderPkg;

const HOST = process.env.MC_HOST || "127.0.0.1";
const PORT = Number(process.env.MC_PORT || 25565);
const USERNAME = process.env.MC_USERNAME || "LuoBot";
const VERSION = process.env.MC_VERSION || "1.21.8";
const WS_PORT = Number(process.env.MC_WS_PORT || 3002);

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

function follow(username, quiet = false) {
  const player = bot.players[username];
  if (!player || !player.entity) {
    throw new Error(`看不到 ${username}`);
  }
  bot.pathfinder.setMovements(movements());
  bot.pathfinder.setGoal(new goals.GoalFollow(player.entity, 2), true);
  if (!quiet) say(`跟着 ${username}`);
  return { ok: true, player: username };
}

function goto(x, y, z, quiet = false) {
  const [nx, ny, nz] = [Number(x), Number(y), Number(z)];
  if ([nx, ny, nz].some(Number.isNaN)) {
    throw new Error("坐标必须是数字");
  }
  bot.pathfinder.setMovements(movements());
  bot.pathfinder.setGoal(new goals.GoalBlock(nx, ny, nz));
  if (!quiet) say(`去 ${nx} ${ny} ${nz}`);
  return { ok: true, position: { x: nx, y: ny, z: nz } };
}

function stateSummary() {
  if (!bot.entity) {
    return { spawned: false };
  }
  const p = bot.entity.position;
  const players = Object.keys(bot.players).filter((n) => n !== bot.username);
  const inventory = bot.inventory.items().map((item) => ({
    name: item.name,
    count: item.count,
  }));
  return {
    spawned: true,
    position: { x: p.x, y: p.y, z: p.z },
    health: bot.health,
    food: bot.food,
    players,
    inventory,
  };
}

async function executeSkill(skill, args = {}) {
  switch (skill) {
    case "state":
      return stateSummary();
    case "follow":
      return follow(String(args.player || ""), true);
    case "stop":
      bot.pathfinder.setGoal(null);
      return { ok: true };
    case "goto":
      return goto(args.x, args.y, args.z, true);
    case "say":
      say(String(args.text || ""));
      return { ok: true };
    default:
      throw new Error(`unknown skill: ${skill}`);
  }
}

const wss = new WebSocketServer({ host: "127.0.0.1", port: WS_PORT });
const clients = new Set();

function broadcast(payload) {
  const text = JSON.stringify(payload);
  for (const ws of clients) {
    if (ws.readyState === 1) {
      ws.send(text);
    }
  }
}

wss.on("connection", (ws) => {
  clients.add(ws);
  ws.on("close", () => clients.delete(ws));
  ws.on("message", async (raw) => {
    let req;
    try {
      req = JSON.parse(raw.toString());
    } catch {
      return;
    }
    if (req.type !== "call") return;
    try {
      const data = await executeSkill(req.skill, req.args || {});
      ws.send(JSON.stringify({ type: "result", id: req.id, ok: true, data }));
    } catch (err) {
      ws.send(
        JSON.stringify({
          type: "result",
          id: req.id,
          ok: false,
          error: String(err?.message || err),
        })
      );
    }
  });
});

console.log(`[bot] ws api on 127.0.0.1:${WS_PORT}`);

bot.once("spawn", () => {
  const p = bot.entity.position;
  console.log(`[bot] spawned at ${p.x} ${p.y} ${p.z}`);
  say("我进来了");
  broadcast({
    type: "event",
    event: "spawn",
    data: { position: { x: p.x, y: p.y, z: p.z } },
  });
});

bot.on("error", (err) => console.error("[bot] error", err));
bot.on("kicked", (reason) => console.error("[bot] kicked", reason));
bot.on("end", (reason) => console.log("[bot] end", reason));

bot.on("death", () => {
  broadcast({ type: "event", event: "death", data: {} });
});

bot.on("playerJoined", (player) => {
  if (player.username === bot.username) return;
  broadcast({
    type: "event",
    event: "player_joined",
    data: { username: player.username },
  });
});

bot.on("playerLeft", (player) => {
  broadcast({
    type: "event",
    event: "player_left",
    data: { username: player.username },
  });
});

bot.on("chat", (username, message) => {
  if (username === bot.username) return;
  broadcast({
    type: "event",
    event: "chat",
    data: { username, message },
  });

  const [cmd, ...args] = message.trim().split(/\s+/);
  if (cmd === "!follow") {
    try {
      follow(args[0] || username);
    } catch (err) {
      say(String(err?.message || err));
    }
  } else if (cmd === "!stop") {
    bot.pathfinder.setGoal(null);
    say("停了");
  } else if (cmd === "!goto") {
    try {
      goto(args[0], args[1], args[2]);
    } catch (err) {
      say(String(err?.message || err));
    }
  } else if (cmd === "!state") {
    const p = bot.entity.position;
    say(
      `我在 ${p.x.toFixed(1)} ${p.y.toFixed(1)} ${p.z.toFixed(1)}，血量 ${bot.health}`
    );
  } else if (cmd === "!say") {
    say(args.join(" "));
  }
});
