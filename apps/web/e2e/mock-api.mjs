import { createServer } from "node:http";

const PORT = Number(process.env.MOCK_API_PORT ?? 8100);

const SESSIONS = {
  S_MATH_E2E: {
    problem_id: "P_E2E_MATH",
    problem_title: "解方程",
    problem_text: "解方程 x+1=2x。",
    subject: "math",
    prompt: {
      action: "ask",
      question: "你会先移项还是先合并同类项？",
      options: ["先移项", "先合并同类项"],
      hint_level: 0,
      reason_code: "DISCRIMINATE_HYPOTHESIS",
      confidence: 0.45,
    },
  },
  S_PHYS_E2E: {
    problem_id: "P_E2E_PHYSICS",
    problem_title: "光滑斜面",
    problem_text: "质量 m=2 kg 的物块从光滑斜面顶端由静止下滑，求底端速度。",
    subject: "physics",
    prompt: {
      action: "ask",
      question: "光滑斜面上物块受几个力？",
      options: ["重力、支持力", "重力、支持力、下滑力"],
      hint_level: 0,
      reason_code: "DISCRIMINATE_HYPOTHESIS",
      confidence: 0.45,
    },
  },
  S_CARD_E2E: {
    problem_id: "P_E2E_CARD",
    problem_title: "恒成立与最值",
    problem_text: "若对任意 x>0，不等式 ln x - a x ≤ 0 恒成立，求 a 的取值范围。",
    subject: "math",
    prompt: null,
    diagnosis: {
      version: "0.1",
      session_id: "S_CARD_E2E",
      problem_id: "P_E2E_CARD",
      card: {
        layer: "L2",
        label: "概念不清：恒成立与最值",
        node_id: "n6",
        one_line: "漏掉了 a≤0 这一支。",
        evidence: ["把恒成立直接当成判别式问题。"],
        excluded: [],
        confidence: 0.86,
        confidence_label: "high",
        next_action: {
          type: "micro_lesson",
          concept_id: "C_MAX_MIN",
          duration_min: 5,
          task_id: null,
        },
        verify: { type: "transfer", due_hours: 24, item_id: null },
        disagree: false,
      },
    },
  },
};

const REVIEW_ITEMS = [
  {
    session_id: "S_REVIEWE2E01",
    problem_id: "P_PUB_002",
    layer: "L2",
    label: "概念不清：恒成立与最值",
    node_id: "n3",
    one_line: "漏掉了 a≤0 这一支。",
    confidence: 0.86,
    created_at: "2026-10-31T08:00:00+00:00",
  },
  {
    session_id: "S_REVIEWE2E02",
    problem_id: "P_PUB_003",
    layer: "L1",
    label: "概念不清：没有抓住关键条件",
    node_id: "n2",
    one_line: "只讨论了 a>0。",
    confidence: 0.74,
    created_at: "2026-10-30T09:30:00+00:00",
  },
];

function sessionBody(id) {
  const preset = SESSIONS[id];
  const diagnosis = preset.diagnosis ?? null;
  return {
    session_id: id,
    state: diagnosis ? "DIAGNOSE" : "PROBE",
    ...preset,
    mode: "learning",
    turn: 0,
    max_turns: 6,
    diagnosis,
    hint: null,
    notice: null,
    progress: {
      turn: 0,
      max_turns: 6,
      confidence: 0.45,
      top_hypothesis: "H_L1",
    },
    history: [],
  };
}

function send(res, status, body) {
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "content-type",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  });
  res.end(body === undefined ? "" : JSON.stringify(body));
}

function verdict(status, detail, findings = []) {
  return { version: "0.3", status, detail, findings };
}

function mathVerdict(step) {
  if (step.includes("x+1=2x")) {
    return verdict("fail", "这个等号不成立：x=0.1 时左边 1.1、右边 0.2。", [
      {
        kind: "identity",
        left: "x+1",
        right: "2*x",
        summary: "x=0.1 时左边 1.1、右边 0.2",
        counterexample: "x=0.1 时左边 1.1、右边 0.2",
      },
    ]);
  }
  return verdict(
    "unknown",
    "没找到可证伪的等号；没判出来不等于这一步正确。",
  );
}

function physicsVerdict(body) {
  const data = body?.data;
  const expected = data?.expected;
  const tolerance = data?.tolerance;
  const shapeOk =
    data?.expression === "sqrt(2*g*h)" &&
    data?.unit === "m/s" &&
    data?.units?.g === "m/s^2" &&
    data?.units?.h === "m" &&
    data?.values?.g === 10 &&
    data?.values?.h === 2 &&
    expected?.unit === "m/s" &&
    typeof expected?.value === "number" &&
    tolerance?.relative === 0.01 &&
    tolerance?.absolute === 0.01;
  if (!shapeOk) {
    return {
      status: 400,
      body: {
        detail:
          "mock API expected expression sqrt(2*g*h), g=10, h=2, expected m/s and relative/absolute tolerance 0.01.",
      },
    };
  }
  if (expected.value === 6.3246) {
    return {
      status: 200,
      body: verdict(
        "pass",
        "表达式量纲 m/s 与声明单位 'm/s' 一致；求值 6.32456（SI）；声明结果值与单位一致",
      ),
    };
  }
  if (expected.value === 7) {
    return {
      status: 200,
      body: verdict(
        "fail",
        "结果值不一致：声明 7（m/s）与表达式 6.32456（SI）相差 0.675445，超过容差 (绝对 1e-09 / 相对 0.01)",
        [
          {
            kind: "quantity",
            left: "声明结果 7（m/s）",
            right: "表达式 6.32456（SI）",
            summary:
              "结果值不一致：声明 7（m/s）与表达式 6.32456（SI）相差 0.675445，超过容差 (绝对 1e-09 / 相对 0.01)",
            counterexample: "",
          },
        ],
      ),
    };
  }
  return {
    status: 200,
    body: verdict(
      "unknown",
      "声明结果与表达式求值无法比较；这不等于这一步正确。",
    ),
  };
}

async function readJson(req) {
  let raw = "";
  for await (const chunk of req) raw += chunk;
  return raw ? JSON.parse(raw) : {};
}

const server = createServer(async (req, res) => {
  if (req.method === "OPTIONS") {
    send(res, 204);
    return;
  }
  const url = new URL(req.url ?? "/", `http://${req.headers.host}`);

  if (req.method === "GET" && url.pathname === "/health") {
    send(res, 200, { status: "ok" });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/v1/review/items") {
    send(res, 200, { version: "0.1", items: REVIEW_ITEMS });
    return;
  }

  if (req.method === "GET" && url.pathname === "/api/v1/knowledge/search") {
    const q = url.searchParams.get("q") ?? "";
    const subject = url.searchParams.get("subject");
    const hits =
      q.includes("恒成立") && subject !== "physics"
        ? [
            {
              card_id: "K_MATH_MAX_MIN",
              title: "恒成立先转成最值",
              excerpt:
                "对定义域内的所有 x，f(x)≤a 恒成立，等价于 f 的最大值≤a；先确认定义域和端点是否取到。",
              source: {
                title: "OpenStax Calculus Volume 1",
                url: "https://openstax.org/details/books/calculus-volume-1",
                license: "CC BY-NC-SA 4.0",
              },
              score: 0.7516,
            },
          ]
        : [];
    send(res, 200, { version: "0.1", enabled: true, query: q, hits });
    return;
  }

  const match = url.pathname.match(
    /^\/api\/v1\/sessions\/([^/]+)(\/steps)?$/,
  );
  if (!match) {
    send(res, 404, { detail: "not found" });
    return;
  }

  const id = decodeURIComponent(match[1]);
  if (!SESSIONS[id]) {
    send(res, 404, { detail: "unknown session" });
    return;
  }

  if (req.method === "GET" && !match[2]) {
    send(res, 200, sessionBody(id));
    return;
  }

  if (req.method === "POST" && match[2]) {
    let body;
    try {
      body = await readJson(req);
    } catch {
      send(res, 400, { detail: "invalid json" });
      return;
    }
    const result =
      SESSIONS[id].subject === "physics"
        ? physicsVerdict(body)
        : { status: 200, body: mathVerdict(String(body.text ?? "")) };
    send(res, result.status, result.body);
    return;
  }

  send(res, 405, { detail: "method not allowed" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock api listening on http://127.0.0.1:${PORT}`);
});
