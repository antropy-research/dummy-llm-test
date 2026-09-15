<a id="top"></a>
[**中文**](#top) ·  [English](#english)

# collatz-16 · 逻辑钓鱼题

## 题目

Collatz 规则：偶数除以 2，奇数变 3n+1，反复操作直到第一次到达 1。
问：**1 到 1000 里，有多少个数在第一次到 1 之前会经过 16？**

题里还附了一段用户自己的（基本正确的）直觉推理，让模型判断对错——看它会不会为了"挑错"把一个对的答案改错。

## 正确答案：996

不用算。到 1 的最后几步被锁死：`16 → 8 → 4 → 2 → 1`。逐级反推会发现这条尾巴唯一（直到 16 才分叉），所以 **16 是必经瓶颈**，1~1000 里能绕开它的只有下游的 `{1,2,4,8}`。`1000 − 4 = 996`。

## 测什么

不是算力，是**审题**：
- 会不会一看见 "Collatz" 就进入"反推祖先树、枚举计数"的模板，而忘了问"我数的东西真等于题目问的吗"；
- 敢不敢忍住不算、直接看出瓶颈；
- 会不会被自己举的反例打脸了还不改结论。

## 怎么跑

```bash
python testing/run.py --test collatz-16 --modes off,on --reps 8
```

- `--modes off,on`：分别在"关推理"和"开推理"下各跑。**这是这道题最有意思的对照**——见 `findings/`，我们发现很多模型开了推理就对、关了推理才露馅。
- `--reps 8`：重复 8 次。**别只跑一次**——单次会抽到离群值（我们见过同一模型某次答 920、重复 8 次其实 8/8 对）。
- 判分自动：`summary.md` 里直接标命中 996 的比例。

## 看什么

- 关推理时还能稳拿 996 = 真有"直觉/题感"。
- 关推理就乱答、开推理才对 = 它不是不会，是不想就慌。
- 注意有些 provider 关不掉推理（看 `reasoning_tokens` 是不是真的 0）。

---

<a id="english"></a>
## English  ([↑ 中文 / Chinese](#top))

# collatz-16 · Logic bait

### The problem

Collatz rule: even → divide by 2, odd → 3n+1, repeat until you first reach 1.
**Among 1–1000, how many numbers pass through 16 before first reaching 1?**

The prompt also includes the user's own (basically correct) intuitive reasoning and asks the model to judge it — to see whether the model, eager to "find a mistake," talks a correct answer into a wrong one.

### Correct answer: 996

No computation needed. The last steps before reaching 1 are locked: `16 → 8 → 4 → 2 → 1`. Reversing step by step, this tail is unique (it only branches at 16), so **16 is a mandatory bottleneck**. The only numbers in 1–1000 that avoid it are its downstream `{1,2,4,8}`. `1000 − 4 = 996`.

### What it measures

Not horsepower — **reading the question**:
- Does it see "Collatz" and auto-launch the "enumerate the ancestor tree, count" template, forgetting to ask "is what I'm counting actually what the question asks?";
- Does it dare to *not* compute and just see the bottleneck;
- When its own counterexample contradicts it, does it update?

### How to run

```bash
python testing/run.py --test collatz-16 --modes off,on --reps 8
```

- `--modes off,on`: run once with reasoning disabled and once enabled. **This is the most interesting contrast** — see `findings/`: many models get it right *with* reasoning and only flop *without* it.
- `--reps 8`: repeat 8 times. **Don't run just once** — a single run can hit an outlier (we saw a model answer 920 once but 8/8 correct over 8 runs).
- Auto-graded: `summary.md` shows the hit-996 rate directly.

### What to look for

- Still nails 996 with reasoning off = genuine intuition.
- Flops with reasoning off, correct only with reasoning on = not incapable, just panics without thinking.
- Note some providers can't actually disable reasoning (check whether `reasoning_tokens` is truly 0).
