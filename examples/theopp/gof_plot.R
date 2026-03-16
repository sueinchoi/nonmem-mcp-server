library(ggplot2)
library(dplyr)

# Read NONMEM table (skip header line)
sdtab <- read.table("sdtab001", header = TRUE, skip = 1)

# Remove rows where DV (CP) is missing or zero (dose records)
obs <- sdtab %>% filter(!is.na(CP) & CP != 0 & PRED != 0)

# Theme
theme_gof <- theme_bw(base_size = 14) +
  theme(
    plot.title = element_text(face = "bold", size = 13),
    panel.grid.minor = element_blank()
  )

# 1. DV vs PRED
p1 <- ggplot(obs, aes(x = PRED, y = CP)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_abline(slope = 1, intercept = 0, linetype = "solid", color = "black") +
  labs(x = "Population Predicted (PRED)", y = "Observed (DV)",
       title = "DV vs PRED") +
  coord_equal() +
  theme_gof

# 2. WRES vs PRED
p2 <- ggplot(obs, aes(x = PRED, y = WRES)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_hline(yintercept = 0, linetype = "solid", color = "black") +
  geom_hline(yintercept = c(-2, 2), linetype = "dashed", color = "red") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.8) +
  labs(x = "Population Predicted (PRED)", y = "WRES",
       title = "WRES vs PRED") +
  theme_gof

# 3. WRES vs TIME
p3 <- ggplot(obs, aes(x = TIME, y = WRES)) +
  geom_point(alpha = 0.6, size = 2, color = "steelblue") +
  geom_hline(yintercept = 0, linetype = "solid", color = "black") +
  geom_hline(yintercept = c(-2, 2), linetype = "dashed", color = "red") +
  geom_smooth(method = "loess", se = FALSE, color = "red", linewidth = 0.8) +
  labs(x = "Time (hr)", y = "WRES",
       title = "WRES vs TIME") +
  theme_gof

# 4. QQ plot of WRES
p4 <- ggplot(obs, aes(sample = WRES)) +
  stat_qq(alpha = 0.6, size = 2, color = "steelblue") +
  stat_qq_line(color = "black") +
  labs(x = "Theoretical Quantiles", y = "Sample Quantiles (WRES)",
       title = "QQ Plot of WRES") +
  theme_gof

# 5. DV & PRED vs TIME by ID (first 6 subjects)
first_ids <- unique(obs$ID)[1:6]
obs_sub <- obs %>% filter(ID %in% first_ids)

p5 <- ggplot(obs_sub, aes(x = TIME)) +
  geom_point(aes(y = CP), size = 2, color = "steelblue") +
  geom_line(aes(y = PRED), color = "red", linewidth = 0.8) +
  facet_wrap(~ID, scales = "free_y", ncol = 3) +
  labs(x = "Time (hr)", y = "Concentration",
       title = "Individual Profiles (DV=blue dots, PRED=red line)") +
  theme_gof

# Save combined GOF
png("gof_run001.png", width = 1200, height = 1000, res = 150)
gridExtra::grid.arrange(p1, p2, p3, p4, ncol = 2)
dev.off()

# Save individual profiles
png("individual_profiles_run001.png", width = 1200, height = 800, res = 150)
print(p5)
dev.off()

cat("GOF plots saved: gof_run001.png, individual_profiles_run001.png\n")
