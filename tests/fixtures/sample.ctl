$PROBLEM 2-Compartment PK Model with First-Order Absorption
$INPUT ID TIME AMT DV MDV EVID WT AGE SEX CL_CR
$DATA ../data/pk_data.csv IGNORE=@
$SUBROUTINES ADVAN4 TRANS4

$PK
  TVCL = THETA(1) * (WT/70)**0.75
  TVV2 = THETA(2)
  TVKA = THETA(3)
  TVQ  = THETA(4)
  TVV3 = THETA(5)

  CL = TVCL * EXP(ETA(1))
  V2 = TVV2 * EXP(ETA(2))
  KA = TVKA * EXP(ETA(3))
  Q  = TVQ
  V3 = TVV3

  S2 = V2

$ERROR
  IPRED = F
  W = SQRT(THETA(6)**2 + (THETA(7)*IPRED)**2)
  IF(W.EQ.0) W = 1
  IRES = DV - IPRED
  IWRES = IRES / W
  Y = IPRED + W * EPS(1)

$THETA
  (0, 5.0, 50)    ; CL (L/h)
  (0, 50, 500)    ; V2 (L)
  (0, 1.5, 10)    ; KA (1/h)
  (0, 3.0, 30)    ; Q (L/h)
  (0, 80, 800)    ; V3 (L)
  (0, 0.5)        ; Additive error
  (0, 0.15)       ; Proportional error

$OMEGA BLOCK(2)
  0.09            ; IIV CL
  0.01 0.09       ; IIV V2
$OMEGA
  0.25            ; IIV KA

$SIGMA
  1 FIX           ; Residual error (scaled by W)

$ESTIMATION METHOD=1 INTERACTION MAXEVAL=9999 SIGDIGITS=3 PRINT=5
$COVARIANCE UNCONDITIONAL
$TABLE ID TIME DV PRED IPRED CWRES IWRES NOPRINT ONEHEADER FILE=sdtab001
$TABLE ID CL V2 KA Q V3 ETA1 ETA2 ETA3 NOPRINT ONEHEADER FILE=patab001
