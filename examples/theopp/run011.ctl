$PROB  THEO 2-COMP + IIV on V2 + CL
$INPUT      ID DOSE=AMT TIME CP=DV WT
$DATA       THEOPP

$SUBROUTINES  ADVAN4 TRANS4

$PK
   CALLFL=1
   CL = THETA(1)*EXP(ETA(1))
   V2 = THETA(2)*EXP(ETA(2))
   Q  = THETA(3)
   V3 = THETA(4)
   KA = THETA(5)
   S2 = V2

$THETA
  (0.001, 0.038, 5)   ; CL
  (0.01, 0.097, 10)   ; V2
  (0.001, 0.120, 5)   ; Q
  (0.01, 0.301, 10)   ; V3
  (0.1, 0.401, 10)    ; KA

$OMEGA
  0.1                ; IIV on CL
  0.39               ; IIV on V2

$ERROR
  Y = F + EPS(1)

$SIGMA  1.14

$EST METHOD=0 MAXEVAL=9999 PRINT=5 NOABORT SIGDIGITS=3
$COV
