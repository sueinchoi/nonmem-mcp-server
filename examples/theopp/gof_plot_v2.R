library(ggplot2)
library(dplyr)

# Read NONMEM table
sdtab <- read.table("sdtab015", header = TRUE, skip = 1)

# Remove dose/missing records
obs <- sdtab %>% filter(!is.na(CP) & CP != 0 & PRED != 0)

theme_gof <- theme_bw(base_size = 13) +
  theme(
    plot.title = element_text(face = "bold", size = 12),
    panel.grid.minor = element_blank()
  )

lim_conc <- c(0, max(obs$CP, obs$IPRED, obs$PRED) * 1.05)

# 1. DV vs PRED
p1 <- ggplot(obs, aes(x = PRED, y = CP)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_abline(slope = 1, intercept = 0, color = "black") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.7) +
  coord_equal(xlim = lim_conc, ylim = lim_conc) +
  labs(x = "PRED", y = "DV", title = "DV vs PRED") +
  theme_gof

# 2. DV vs IPRED
p2 <- ggplot(obs, aes(x = IPRED, y = CP)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_abline(slope = 1, intercept = 0, color = "black") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.7) +
  coord_equal(xlim = lim_conc, ylim = lim_conc) +
  labs(x = "IPRED", y = "DV", title = "DV vs IPRED") +
  theme_gof

# 3. CWRES vs PRED
p3 <- ggplot(obs, aes(x = PRED, y = CWRES)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_hline(yintercept = 0, color = "black") +
  geom_hline(yintercept = c(-2, 2), linetype = "dashed", color = "red") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.7) +
  labs(x = "PRED", y = "CWRES", title = "CWRES vs PRED") +
  theme_gof

# 4. CWRES vs TIME
p4 <- ggplot(obs, aes(x = TIME, y = CWRES)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_hline(yintercept = 0, color = "black") +
  geom_hline(yintercept = c(-2, 2), linetype = "dashed", color = "red") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.7) +
  labs(x = "Time (hr)", y = "CWRES", title = "CWRES vs TIME") +
  theme_gof

# 5. QQ plot of CWRES
p5 <- ggplot(obs, aes(sample = CWRES)) +
  stat_qq(alpha = 0.6, size = 2, color = "steelblue") +
  stat_qq_line(color = "black") +
  labs(x = "Theoretical Quantiles", y = "CWRES",
       title = "QQ Plot of CWRES") +
  theme_gof

# 6. |IWRES| vs IPRED
p6 <- ggplot(obs, aes(x = IPRED, y = abs(IWRES))) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.7) +
  labs(x = "IPRED", y = "|IWRES|", title = "|IWRES| vs IPRED") +
  theme_gof

# Save 6-panel GOF
png("gof_run015.png", width = 1400, height = 1000, res = 150)
gridExtra::grid.arrange(p1, p2, p3, p4, p5, p6, ncol = 3)
dev.off()

# Individual profiles with IPRED (first 6 subjects)
first_ids <- unique(obs$ID)[1:6]
obs_sub <- obs %>% filter(ID %in% first_ids)

p7 <- ggplot(obs_sub, aes(x = TIME)) +
  geom_point(aes(y = CP), size = 2.5, color = "steelblue") +
  geom_line(aes(y = IPRED), color = "red", linewidth = 0.9) +
  geom_line(aes(y = PRED), color = "grey50", linewidth = 0.7, linetype = "dashed") +
  facet_wrap(~ID, scales = "free_y", ncol = 3) +
  labs(x = "Time (hr)", y = "Concentration",
       title = "Individual Profiles (DV=blue, IPRED=red, PRED=grey dashed)") +
  theme_gof

png("individual_profiles_run015.png", width = 1200, height = 800, res = 150)
print(p7)
dev.off()

cat("Done: gof_run015.png, individual_profiles_run015.png\n")
