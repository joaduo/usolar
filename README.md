# usolar
Micropython solar charger monitoring


```
                                  100kR
┌─────────────┐     Blue
│             ├──────────────────┬─────── +
│             │GPIO36        7kR │          Panels 50v
│             │                  └───┬─── -
│             │                      │
│             │                      │100kR
│             │ Ground Green         │
│    ESP32    ├──────────────────────┤
│             │ -                    │
│             │                      │
│             │                      │5kR
│             │                      │
│             │              3kR ┌───┴─── -
│             │GPIO39            │          Charger 5V
│             ├──────────────────┴─────── +
└─────────────┘    Red             2kR
```