import minecraftData from "minecraft-data";
import mineflayer from "mineflayer";
import collectBlockPkg from "mineflayer-collectblock";
import pathfinderPkg from "mineflayer-pathfinder";
import { WebSocketServer } from "ws";

const { pathfinder, Movements, goals } = pathfinderPkg;
const { plugin: collectBlockPlugin } = collectBlockPkg;

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
bot.loadPlugin(collectBlockPlugin);

function say(text) {
  bot.chat(text);
}

// ---------- 中文名 -> 方块/物品 ----------

const LOG = (name) => name.endsWith("_log");

const BLOCK_ALIASES = {
  木头: LOG,
  原木: LOG,
  树: LOG,
  橡木: (name) => name === "oak_log",
  白桦: (name) => name === "birch_log",
  云杉: (name) => name === "spruce_log",
  石头: (name) => name === "stone",
  圆石: (name) => name === "cobblestone",
  泥土: (name) => name === "dirt",
  沙子: (name) => name === "sand",
  砂子: (name) => name === "sand",
  草方块: (name) => name === "grass_block",
  煤矿: (name) => name.endsWith("coal_ore"),
  铁矿: (name) => name.endsWith("iron_ore"),
  铜矿: (name) => name.endsWith("copper_ore"),
  金矿: (name) => name.endsWith("gold_ore"),
  钻石: (name) => name.endsWith("diamond_ore"),
  小麦: (name) => name === "wheat",
  南瓜: (name) => name === "pumpkin",
  甘蔗: (name) => name === "sugar_cane",
  蘑菇: (name) => name.endsWith("mushroom"),
};

const ITEM_ALIASES = {
  木头: LOG,
  原木: LOG,
  橡木: (name) => name === "oak_log",
  石头: (name) => name === "stone" || name === "cobblestone",
  圆石: (name) => name === "cobblestone",
  泥土: (name) => name === "dirt",
  沙子: (name) => name === "sand",
  煤矿: (name) => name === "coal",
  铁锭: (name) => name === "iron_ingot",
  粗铁: (name) => name === "raw_iron",
  镐子: (name) => name.endsWith("_pickaxe"),
  斧子: (name) => name.endsWith("_axe"),
  铲子: (name) => name.endsWith("_shovel"),
  剑: (name) => name.endsWith("_sword"),
  木棍: (name) => name === "stick",
  面包: (name) => name === "bread",
  苹果: (name) => name === "apple",
};

const ITEM_NAMES = {
   oak_log: "橡木",
  birch_log: "白桦木",
  spruce_log: "云杉木",
  jungle_log: "丛林木",
  acacia_log: "金合欢木",
  dark_oak_log: "深色橡木",
  mangrove_log: "红树木",
  cherry_log: "樱花木",
  stone: "石头",
  cobblestone: "圆石",
  dirt: "泥土",
  sand: "沙子",
  gravel: "砂砾",
  coal: "煤",
  raw_iron: "粗铁",
  iron_ingot: "铁锭",
  wheat: "小麦",
  wheat_seeds: "小麦种子",
  stick: "木棍",
  oak_planks: "橡木木板",
  oak_sapling: "橡树苗",
  birch_sapling: "白桦树苗",
  spruce_sapling: "云杉树苗",
  coal_ore: "煤矿石",
  iron_ore: "铁矿石",
  raw_copper: "粗铜",
  apple: "苹果",
  bread: "面包",
  egg: "鸡蛋",
  leather: "皮革",
  feather: "羽毛",
};

function displayName(name) {
  return ITEM_NAMES[name] || name;
}

function matcherFor(query, aliases) {
  const key = String(query || "").trim().toLowerCase();
  if (!key) throw new Error("没说要什么");
  const alias = aliases[key];
  if (alias) return alias;
  return (name) => name === key || name.includes(key);
}

function findBlocks(query, count) {
  const match = matcherFor(query, BLOCK_ALIASES);
  const positions = bot.findBlocks({
    matching: (block) => match(block.name),
    maxDistance: 48,
    count: Math.max(1, count),
  });
  return positions
    .map((pos) => bot.blockAt(pos))
    .filter((block) => block != null);
}

function inventoryCounts() {
  const counts = new Map();
  if (!bot.inventory) return counts;
  for (const item of bot.inventory.items()) {
    counts.set(item.name, (counts.get(item.name) || 0) + item.count);
  }
  return counts;
}

function diffCounts(before, after) {
  const gained = [];
  for (const [name, count] of after) {
    const delta = count - (before.get(name) || 0);
    if (delta > 0) gained.push([name, delta]);
  }
  return gained.sort((a, b) => b[1] - a[1]);
}

function findInventoryItem(query) {
  const match = matcherFor(query, ITEM_ALIASES);
  const items = (bot.inventory?.items() || []).filter((item) =>
    match(item.name)
  );
  if (!items.length) return null;
  return items.sort((a, b) => b.count - a.count)[0];
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
  cancelCurrentAction();
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
  cancelCurrentAction();
  bot.pathfinder.setMovements(movements());
  bot.pathfinder.setGoal(new goals.GoalBlock(nx, ny, nz));
  if (!quiet) say(`去 ${nx} ${ny} ${nz}`);
  return { ok: true, position: { x: nx, y: ny, z: nz } };
}

// ---------- 后台动作：采集 / 送东西 ----------
// 长动作不阻塞 WS，调用立刻返回；做完通过 action_done 事件通知 Python。

let activeAction = null;
let actionSeq = 0;

function cancelCurrentAction() {
  const action = activeAction;
  if (action == null) return false;
  activeAction = null;
  action.cancelled = true;
  clearTimeout(action.timer);
  console.log(`[action] cancel ${action.kind}`);
  try {
    action.cancel?.();
  } catch {
    // 取消失败不影响新动作
  }
  return true;
}

function startAction(kind, label, run, timeoutMs = 120000) {
  if (!bot.entity) throw new Error("还没进服");
  cancelCurrentAction();
  const state = {
    id: ++actionSeq,
    kind,
    cancelled: false,
    timer: null,
    cancel: null,
  };
  activeAction = state;
  console.log(`[action] start ${kind} (${label})`);
  const finish = (event, data) => {
    if (activeAction !== state) return;
    activeAction = null;
    clearTimeout(state.timer);
    console.log(`[action] ${event} ${kind}`, data);
    broadcast({ type: "event", event, data: { kind, ...data } });
  };
  state.timer = setTimeout(() => {
    state.cancelled = true;
    try {
      state.cancel?.();
    } catch {
      // 忽略
    }
    finish("action_failed", { error: `${label}太久了，先停下` });
  }, timeoutMs);
  run(state)
    .then((summary) => {
      if (state.cancelled) return;
      finish("action_done", { summary });
    })
    .catch((err) => {
      if (state.cancelled) return;
      finish("action_failed", {
        error: String(err?.message || err),
      });
    });
  return { started: true, kind };
}

function clampInt(raw, min, max, fallback) {
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, value));
}

function withTimeout(promise, ms, onTimeout) {
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      try {
        onTimeout?.();
      } catch {
        // 忽略超时清理错误
      }
      reject(new Error("超时"));
    }, ms);
  });
  return Promise.race([promise, timeout]).finally(
    () => clearTimeout(timer)
  );
}

function startCollect(query, countRaw) {
  const count = clampInt(countRaw, 1, 16, 4);
  const targets = findBlocks(query, count);
  if (!targets.length) {
    throw new Error(`附近没找到${query}`);
  }
  const before = inventoryCounts();
  return startAction(
    "collect",
    `挖${query}`,
    async (state) => {
      state.cancel = () => {
        bot.collectBlock.cancelTask().catch(() => {});
        bot.pathfinder.setGoal(null);
      };
      const started = Date.now();
      let gained = [];
      for (const target of targets) {
        if (state.cancelled) throw new Error("已取消");
        if (Date.now() - started > 40000) break;
        try {
          // 一块一块挖：某棵树够不着时不会把整单卡死
          await withTimeout(
            bot.collectBlock.collect([target], { ignoreNoPath: true }),
            12000,
            () => {
              bot.collectBlock.cancelTask().catch(() => {});
              bot.pathfinder.setGoal(null);
            }
          );
        } catch (err) {
          if (String(err?.message) === "超时") continue;
          throw err;
        }
        gained = diffCounts(before, inventoryCounts());
        const total = gained.reduce((sum, [, n]) => sum + n, 0);
        if (total >= count) break;
      }
      if (state.cancelled) throw new Error("已取消");
      if (!gained.length) {
        return `挖了${query}，但没捡到东西。`;
      }
      const text = gained
        .slice(0, 6)
        .map(([name, n]) => `${displayName(name)}x${n}`)
        .join("、");
      return `挖到了 ${text}。`;
    },
    60000
  );
}

function moveNear(position, distance, timeoutMs) {
  bot.pathfinder.setMovements(movements());
  let timer = null;
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(() => {
      bot.pathfinder.stop();
      reject(new Error("走不过去"));
    }, timeoutMs);
  });
  return Promise.race([
    bot.pathfinder.goto(
      new goals.GoalNear(position.x, position.y, position.z, distance)
    ),
    timeout,
  ]).finally(() => clearTimeout(timer));
}

function startGive(username, itemQuery, countRaw) {
  const player = bot.players[username];
  if (!player || !player.entity) {
    throw new Error(`看不到 ${username}`);
  }
  const item = findInventoryItem(itemQuery);
  if (!item) {
    throw new Error(`背包里没有${itemQuery}`);
  }
  const count = clampInt(countRaw, 1, item.count, 1);
  const itemName = item.name;
  return startAction("give", `给${username}${itemQuery}`, async (state) => {
    state.cancel = () => bot.pathfinder.setGoal(null);
    await moveNear(player.entity.position, 2, 20000);
    if (state.cancelled) throw new Error("已取消");
    if (!player.entity) throw new Error(`${username}不在了`);
    if (bot.entity.position.distanceTo(player.entity.position) > 4) {
      throw new Error(`${username}跑远了`);
    }
    const current = findInventoryItem(itemName);
    if (!current) throw new Error(`背包里没有${itemName}了`);
    const n = Math.min(count, current.count);
    await bot.lookAt(player.entity.position.offset(0, 1.6, 0), true);
    await bot.toss(current.type, null, n);
    return `给了 ${username} ${displayName(itemName)}x${n}。`;
  });
}

function inventorySummary() {
  if (!bot.inventory) return { items: [] };
  const counts = [...inventoryCounts().entries()]
    .map(([name, count]) => ({ name: displayName(name), count }))
    .sort((a, b) => b.count - a.count);
  return { items: counts.slice(0, 24), total: counts.length };
}

function stateSummary() {
  if (!bot.entity) {
    return { spawned: false };
  }
  const p = bot.entity.position;
  const players = Object.keys(bot.players).filter((n) => n !== bot.username);
  const inventory = bot.inventory.items().map((item) => ({
    name: displayName(item.name),
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
    case "inventory":
      return inventorySummary();
    case "follow":
      return follow(String(args.player || ""), true);
    case "stop": {
      const cancelled = cancelCurrentAction();
      bot.pathfinder.setGoal(null);
      return { ok: true, cancelled };
    }
    case "goto":
      return goto(args.x, args.y, args.z, true);
    case "collect":
      return startCollect(
        String(args.block || ""),
        args.count
      );
    case "give":
      return startGive(
        String(args.player || ""),
        String(args.item || ""),
        args.count
      );
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

let lastPosition = null;
setInterval(() => {
  if (bot.entity) lastPosition = bot.entity.position.clone();
}, 1000).unref();

bot.on("death", () => {
  broadcast({
    type: "event",
    event: "death",
    data: lastPosition ? { position: lastPosition } : {},
  });
});

bot.on("entityDead", (entity) => {
  if (!entity || entity === bot.entity) return;
  if (entity.username === bot.username) return;
  if (entity.type !== "player" || !entity.username) return;
  broadcast({
    type: "event",
    event: "player_death",
    data: { username: entity.username },
  });
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
