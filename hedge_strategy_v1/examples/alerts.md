# Alert Message Examples

기본 메인 진입:

```text
buy,BTCUSDT.P,1,67250
sell,ETHUSDT.P,0.5,3120
```

확장 메인 진입:

```text
buy,{{ticker}},1,{{close}},regime=bull,role=main,hedge=0,tf=15
sell,{{ticker}},1,{{close}},regime=bear,role=main,hedge=0,tf=15
```

부분 헤지:

```text
sell,{{ticker}},0.25,{{close}},regime=bull,role=hedge,hedge=0.25,tf=15
buy,{{ticker}},0.25,{{close}},regime=bear,role=hedge,hedge=0.25,tf=15
```

헤지 해제:

```text
close,{{ticker}},0.25,{{close}},role=hedge_close
```
