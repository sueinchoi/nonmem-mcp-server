$PROB  THEO 2-COMP BASE MODEL (NO IIV) - INITIAL SET 1
$INPUT      ID DOSE=AMT TIME CP=DV WT
$DATA       THEOPP

$SUBROUTINES  ADVAN4 TRANS4

$PK
; DOSE is mg/kg (weight-adjusted), so PK params are per-kg basis
   CALLFL=1
   CL = THETA(1)
   V2 = THETA(2)
   Q  = THETA(3)
   V3 = THETA(4)
   KA = THETA(5)
   S2 = V2

$THETA
  (0.001, 0.1, 5)     ; CL (L/hr/kg)
  (0.01, 0.5, 10)     ; V2 (L/kg)
  (0.001, 0.05, 5)    ; Q (L/hr/kg)
  (0.01, 0.5, 10)     ; V3 (L/kg)
  (0.1, 3, 10)        ; KA (1/hr)

$OMEGA 0 FIX  ; no IIV

$ERROR
  Y = F + EPS(1)

$SIGMA  0.5

$EST METHOD=0 MAXEVAL=9999 PRINT=5 NOABORT SIGDIGITS=3
$COV
