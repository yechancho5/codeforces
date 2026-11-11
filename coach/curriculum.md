# Curriculum toward 1900

A topic gets **taught** only when evidence says it's missing: a postmortem classified as `knowledge`.
If the same technique shows up missing twice at the frontier, it becomes a **topic block**:
1. learn it from one source
2. implement it from scratch
3. drill 5-10 problems with the tags known
4. go back to mixed practice, where transfer reviews test recognition with tags hidden

Status: `-` not yet relevant · `taught` · `drilled` · `solid` (passed 2+ tag-hidden transfers).
CF tags are for `coach.py pick --tags "..."`. Codeforces has no "prefix sums" tag, so those drills are chosen by hand.
Sources: [USACO Guide](https://usaco.guide), [CSES problem set](https://cses.fi/problemset/), [cp-algorithms](https://cp-algorithms.com).

## Phase 1: 900 → 1200 (Div 3/4 A-C)
| Topic | Status | CF tags | Drills |
|---|---|---|---|
| STL fluency (sort + comparators, map/set, pair) | - | sortings, implementation | CSES 1621 Distinct Numbers, 1084 Apartments |
| Heaps / `priority_queue` | - | data structures, greedy | CSES 1164 Room Allocation, 1091 Concert Tickets (multiset) |
| Prefix sums / difference arrays | - | (none; pick manually) | CSES 1646 Static Range Sum Queries; CF 1807D (reconstruct) |
| Two pointers | - | two pointers | CSES 1640 Sum of Two Values, 1141 Playlist |
| Binary search | - | binary search | CSES 1085 Array Division, 1620 Factory Machines |
| Greedy with sorting | - | greedy, sortings | CSES 1629 Movie Festival |
| Parity / gcd / divisibility | - | math, number theory | - |
| Bitwise basics (xor, and/or, bits) | - | bitmasks | - |

## Phase 2: 1200 → 1500 (Div 2 A-C, Div 3 A-E)
| Topic | Status | CF tags | Drills |
|---|---|---|---|
| BFS / DFS on grids and adjacency lists | - | dfs and similar, graphs | CSES 1192 Counting Rooms, 1193 Labyrinth, 1666 Building Roads, 1667 Message Route, 1668 Building Teams |
| DSU | - | dsu | CSES 1676 Road Construction |
| Binary search on the answer | - | binary search | CSES 1620 Factory Machines |
| Basic DP (1D/2D, knapsack) | - | dp | CSES 1633 Dice Combinations, 1634 Minimizing Coins, 1158 Book Shop |
| Modular arithmetic (power, inverse, sieve) | - | number theory, math | CSES 1095 Exponentiation, 1617 Bit Strings |
| Constructive | - | constructive algorithms | - |
| XOR properties | - | bitmasks | - |

## Phase 3: 1500 → 1700
| Topic | Status | CF tags | Drills |
|---|---|---|---|
| Dijkstra | - | shortest paths, graphs | CSES 1671 Shortest Routes I, 1672 Shortest Routes II |
| Trees: DFS, subtree values, diameter | - | trees, dfs and similar | CSES 1674 Subordinates, 1131 Tree Diameter |
| Harder DP (states, prefix-optimized) | - | dp | - |
| BIT / segment tree basics | - | data structures | CSES 1648 Dynamic Range Sum Queries, 1649 Dynamic Range Minimum Queries |
| Interactive problems | - | interactive | - |

## Phase 4: 1700 → 1900
Mostly speed and insight on Div 2 C/D, not new topics.
| Topic | Status | CF tags | Drills |
|---|---|---|---|
| Observation-heavy C/D | - | constructive algorithms, greedy, math | volume at the frontier |
| Combinatorics mod p | - | combinatorics | - |
| Game theory basics | - | games | - |
| Stress testing (brute vs. solution) | - | - | build `stress.sh` at ~1300 |

## Topic block log
_(date · topic · trigger evidence · drills done · outcome)_
