#include <iostream>
#include <string>
using namespace std;

int main() {

  int n;
  cin >> n;

  for (int i = 0; i < n; i++) {

    int size;
    cin >> size;

    string s;
    cin >> s;

    int l = 0;
    int r = size - 1;

    while  ((((s[l] =='0') && (s[r] == '1')) || ((s[l] == '1') && (s[r] == '0'))) && (l < r)) {
      
      size -= 2;
      l += 1;
      r -= 1;      
    }

    cout << size << '\n';
  }
  return 0;
}
