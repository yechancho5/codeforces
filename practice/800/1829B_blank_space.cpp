#include <iostream>
#include <algorithm>
using namespace std;

int main() {

  int n;
  cin >> n;

  for (int i = 0; i < n; i++) {

    int size;
    cin >> size;
    int longest = 0;
    int current_max = 0;
    
    for (int j = 0; j < size; j++) {

      int current_value;
      cin >> current_value;

      if (current_value == 0) {
        current_max += 1;
        longest = max(current_max, longest);
      } else { current_max = 0;}
      
    }

    cout << longest << '\n';
  }

  return 0;
}
