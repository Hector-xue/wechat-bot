import time, wxui
wxui.move_click(272, 750); time.sleep(1.2)      # 左下菜单
wxui.move_click(375, 625); time.sleep(1.5)      # Manage Chat History
wxui.move_click(700, 411); time.sleep(1.5)      # Export chat history
wxui.move_click(710, 505); time.sleep(6)        # Start
dx = 699; dy = 520
wxui.move_click(dx, dy)                          # Done（如果出现）
