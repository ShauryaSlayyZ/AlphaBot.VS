# Test Plan: LLM-Only Mode Feature

## Pre-Test Checklist
✅ Backend running on port 8000
✅ Frontend running on port 3000  
✅ Ollama running on port 11434
✅ Developer Mode toggle added to UI
✅ No TypeScript errors in page.tsx

## Test Cases

### Test 1: Toggle Developer Mode ON
1. Open http://localhost:3000
2. Look for "Dev Mode" toggle in top-right header
3. Click the toggle switch
4. **Expected**: Purple panel appears below header with engine mode options

### Test 2: Switch to LLM-Only Mode
1. Enable Developer Mode (from Test 1)
2. Find the radio buttons: "Hybrid" and "LLM-Only"
3. Select "LLM-Only" radio button
4. **Expected**: LLM-Only option is selected

### Test 3: Run Query in Hybrid Mode
1. Make sure "Hybrid" is selected
2. Type query: "show me total revenue"
3. Press Enter
4. **Expected**: 
   - Results appear quickly (should be <200ms)
   - Purple panel shows: "⚡ Hybrid (Deterministic)" or "🔀 Hybrid (LLM Fallback)"
   - Execution time shown in milliseconds

### Test 4: Run Same Query in LLM-Only Mode
1. Select "LLM-Only" radio button
2. Type query: "show me total revenue"
3. Press Enter
4. **Expected**:
   - Results appear slower (Ollama processing time)
   - Purple panel shows: "🤖 LLM Only"
   - Execution time higher than Hybrid mode

### Test 5: Compare Complex Query
1. Test in Hybrid: "sales team performance by region"
2. Note the execution time
3. Switch to LLM-Only
4. Run same query: "sales team performance by region"
5. Note the execution time
6. **Expected**: LLM-Only mode should be slower but both should return results

### Test 6: Verify Backend Integration
1. Run any query with LLM-Only enabled
2. Check browser Network tab (F12)
3. Look at the POST request to `/api/query`
4. **Expected**: Request body should contain `"force_llm": true`

### Test 7: Toggle Back to Hybrid
1. Switch from LLM-Only back to Hybrid
2. Run query: "total profit by department"
3. **Expected**: Fast response, deterministic parser should handle it

## Debugging Tips

If queries always show the same engine mode:
- Check browser console for errors
- Verify `forceLLM` state is changing when radio button clicked
- Check Network tab to confirm `force_llm` flag in request

If purple panel doesn't appear:
- Make sure Dev Mode toggle is ON
- Check for CSS/styling issues
- Verify `devMode` state is true

If backend doesn't respect force_llm flag:
- Check backend logs for the flag value
- Verify backend/main.py line 2580 handles force_llm correctly
- Restart backend if needed

## Success Criteria

✅ Dev Mode toggle works  
✅ Purple panel appears when Dev Mode is ON  
✅ Radio buttons switch between Hybrid and LLM-Only  
✅ Queries in Hybrid mode use deterministic parser (faster)  
✅ Queries in LLM-Only mode use Ollama (slower but always LLM)  
✅ Engine mode indicator shows correct mode  
✅ Execution time is displayed  
✅ No errors in console or backend logs
