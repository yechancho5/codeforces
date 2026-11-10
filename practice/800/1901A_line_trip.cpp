#include <iostream>
using namespace std;

int main() {

  int tests;
  cin >> tests;

  for (int i = 0; i < tests; i++) {

    int n;
    int x;
    cin >> n;
    cin >> x;

    int longest_distance = 0;
    int current_distance = 0;
    int a;
    for (int j = 0; j < n; j++) {

        cin >> a;
        current_distance = a - current_distance;

        longest_distance = max(current_distance, longest_distance);
        current_distance = a;
  
    }

    longest_distance = max(longest_distance, (2 * (x - a)));

    cout << longest_distance << '\n';
    
  }

  return 0;
}
