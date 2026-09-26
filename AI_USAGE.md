# AI usage disclosure


- Tool/model:cursor
- Purpose:  gather all requirments and organize them.
- Files or decisions affected: the steps that i would follow to finish the task
- What you changed or rejected:  
- How you independently verified it: checked all the .md  and verified that ai didn't skip any thing or added any thing
- Related commit: none

- Tool/model:claude
- Purpose:  enhance the docker-compose file 
- Files or decisions affected: docker-compose.yml
- What you changed or rejected:  rejected adding "deploy and resources" entries 
- How you independently verified it: It's valid, but it isn't necessary for the requirements I'm implementing, and adding arbitrary limits could change runtime behavior. Therefore I left it unchanged.
- Related commit: none

- Tool/model:claude
- Purpose:  Writing testing scripts
- Files or decisions affected: validate.py failure.py
- What you changed or rejected:  found it matches what i need so no change.
- How you independently verified it: traced the written lines, checked all needed criterias are in and all test cases are covered finally run the files to see the output.
- Related commit:  <8fa7df0>


