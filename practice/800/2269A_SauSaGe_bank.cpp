#include <iostream>
#include <cmath>
using namespace std;

int main() {

  int n;
  cin >> n;

  for (int i = 0; i < n; i++) {

    int n;
    int k;

    cin >> n;
    cin >> k;

    int max = n - k + 1;

    long int money = pow(2, max);

    k -= 1;

    money += (k * 2);

    cout << money << '\n';
          
  }

  return 0;
}
