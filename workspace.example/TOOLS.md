# TOOLS.md

## Infrastructure
- Gateway port: 8000
- Timezone: Asia/Taipei

## Date & Time

Use `exec` to check dates — no external service needed:

```bash
# Check day of week
date -d "2026-04-01" "+%A"          # Wednesday

# Today's date
date "+%Y-%m-%d %A"

# Generate a month calendar
node -e "const d=new Date(2026,3,1); while(d.getMonth()===3){console.log(d.toISOString().slice(0,10), ['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][d.getDay()]); d.setDate(d.getDate()+1)}"
```

## Notes
- Don't store passwords or tokens in this file
- Environment variables are managed via settings
