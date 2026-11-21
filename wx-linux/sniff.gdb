set pagination off
set confirm off
source /root/dsh/wx-linux/sniff.py
catch syscall pread64
commands
silent
python on_syscall()
continue
end
run
