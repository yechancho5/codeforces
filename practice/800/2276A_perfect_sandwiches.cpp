#include <iostream>
using namespace std;

int main() {
  
  int n;
  cin >> n;
  
  for (int i = 0; i < n; i++) {
    int a;
    int b;

    cin >> a;
    cin >> b;

    int sandwiches = 0;

    if (b >= a) {
      cout << -1 << '\n';
      continue;
    }

    while ((a-b) >= 1 && b > 0) {
      
      a -= 2;
      b -= 1;

      sandwiches += 1;
      
    }

    cout << sandwiches << '\n';
     
  }
  
  return 0;
}
