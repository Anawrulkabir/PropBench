;; Sutherland's law (W. Sutherland, Phil. Mag. 36 (1893) 507):
;;   eta = eta0 (T/T0)^(3/2) (T0 + S) / (T + S)
;; air (F. M. White, Viscous Fluid Flow, 3rd ed. (2006), Table 1-2): eta0 = 1.716e-5 Pa s, T0 = 273.15 K, S = 110.4 K.
;; Plug-in ABI 1: pb_predict(temperature in K, molar density in mol/m3) -> viscosity in Pa s.
(module
  (func (export "pb_predict") (param $t f64) (param $rho f64) (result f64)
    (local $r f64)
    (local.set $r (f64.div (local.get $t) (f64.const 273.15)))
    (f64.mul
      (f64.const 1.716e-5)
      (f64.mul
        (f64.mul (local.get $r) (f64.sqrt (local.get $r)))
        (f64.div (f64.const 383.55) (f64.add (local.get $t) (f64.const 110.4)))))))
