# Playbook

Tricks and rules that make problems faster to crack. The coach pulls tips from here into
each brief, matched to your recent failure types. Your own rules collect at the bottom
(added by `coach.py log --trigger`).

## Read the constraints first

| Constraint | Usually means |
|---|---|
| n ≤ 10 | try all permutations, O(n!·n) |
| n ≤ 20 | bitmask / subsets, O(2ⁿ·n) |
| n ≤ 500 | O(n³) |
| n ≤ 5000 | O(n²) |
| n ≤ 2·10⁵ | O(n log n) or O(n): sort, binary search, prefix sums, two pointers, set/map |
| n ≤ 10⁹ or 10¹⁸ | O(log n) or O(1): math formula, binary search on the answer |
| "sum of n over all test cases ≤ 2·10⁵" | per-test work must be O(n log n); never allocate/clear an array of max size per test |
| values up to 10⁹ | sums and products need `long long` |

## Invariants & observations
- Before coding, solve 3-4 tiny cases by hand. Then write the answer for n = 1..8 and look for the pattern.
- For any operation, ask what never changes: parity, sum, sum mod k, count of something, sorted order, xor of everything.
- Look at the extremes: the maximum element, the minimum element, the first and last positions.
- "Print -1 if impossible": find the exact condition for impossible first. The rest is often easy.
- The answer is often tiny (0, 1, 2, or "YES" in a few cases). Prove why it can't be bigger.
- Does the order of the input matter? If not, sort it.
- "Minimize the maximum" or "maximize the minimum" → binary search on the answer + greedy check.
- Many range queries → prefix sums (prefix xor for xor, difference array for range updates).
- Pairs (i, j) with a condition → fix one side and count the other with a map, sort, or two pointers.
- Stuck on a greedy? Try an exchange argument: if two adjacent choices are swapped, does it get worse?
- Think backwards: start from the final state, or reverse the operation.
- Write a brute force for small n and compare. It finds wrong observations quickly.

## Implementation pitfalls
- Overflow: `int` maxes around 2.1·10⁹. Use `long long` for sums and products. Write `1LL << k`, not `1 << k`.
- `accumulate(v.begin(), v.end(), 0LL)`: with plain `0` the sum is an `int`.
- On a `set`/`map`, call `s.lower_bound(x)`. `lower_bound(s.begin(), s.end(), x)` is O(n).
- Reset every global or reused container between test cases.
- Check n = 1, all elements equal, already-sorted input, and the maximum-size input.
- Fast IO: `ios::sync_with_stdio(false); cin.tie(nullptr);` and `'\n'` instead of `endl`.
- Off-by-one: decide whether indices are 0- or 1-based and stick to it.
- `v.size() - 1` is unsigned: when the vector is empty it is huge. Cast to int: `(int)v.size() - 1`.
- Compile with `scripts/run.sh`: the sanitizers catch out-of-bounds access and overflow on the sample input.

## C++ / STL syntax
```cpp
sort(v.begin(), v.end(), [](const auto& a, const auto& b) { return a.second < b.second; });
priority_queue<int> mx;                                   // max-heap
priority_queue<int, vector<int>, greater<int>> mn;        // min-heap
priority_queue<pair<long long,int>, vector<pair<long long,int>>, greater<>> pq; // Dijkstra
vector<vector<int>> adj(n);  adj[u].push_back(v);         // adjacency list
vector<long long> pre(n + 1); for (int i = 0; i < n; i++) pre[i + 1] = pre[i] + a[i];
auto it = s.lower_bound(x); if (it != s.end()) { /* *it >= x */ }
map<int,int> cnt; for (int x : a) cnt[x]++;
for (auto [key, val] : cnt) { }                           // structured bindings (C++17)
__builtin_popcountll(x);  __builtin_ctzll(x);             // bit counts
int lo = 0, hi = n; while (lo < hi) { int mid = (lo + hi) / 2; if (ok(mid)) hi = mid; else lo = mid + 1; }
```

## Contest & timing
- Read the constraints before the story.
- Go in order. If you're stuck on a problem for 25 minutes, read the next one: it is sometimes easier.
- Before submitting: overflow? n = 1? Multi-test reset? Output format (YES/yes)?
- Wrong answer on test 2+: look for a missed case before rewriting. Write a brute force if it's quick.
- In the last 10 minutes, don't start new ideas. Recheck edge cases on what you have.
- Upsolve the next day: every problem up to one past your last solve.

## Editorial protocol
- Read only until the key idea clicks, then close it and write the code yourself. Never copy code.
- Afterwards, name the missing piece: a technique you didn't know, or an observation you didn't see.
- State the insight in one sentence in your own words. If you can't, you haven't got it yet.

## My trigger rules
