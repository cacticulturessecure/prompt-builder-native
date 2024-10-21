import anthropic
import re
import sys
import os
import subprocess
import tempfile

def read_file(file_path):
    """Read and return the contents of a file."""
    try:
        with open(file_path, 'r') as file:
            content = file.read().strip()
            if content.startswith('ANTHROPIC_API_KEY ='):
                return content.split('=')[1].strip().strip('"')
            return content
    except FileNotFoundError:
        print(f"Error: File '{file_path}' not found.")
        sys.exit(1)
    except IOError:
        print(f"Error: Unable to read file '{file_path}'.")
        sys.exit(1)

def write_file(file_path, content):
    """Write content to a file."""
    try:
        os.makedirs('outputs', exist_ok=True)
        full_path = os.path.join('outputs', file_path)
        with open(full_path, 'w') as file:
            file.write(content)
    except IOError:
        print(f"Error: Unable to write to file '{full_path}'.")
        sys.exit(1)

def extract_between_tags(tag: str, string: str, strip: bool = False) -> list[str]:
    """Extract content between specified XML tags."""
    ext_list = re.findall(f"<{tag}>(.+?)</{tag}>", string, re.DOTALL)
    if strip:
        ext_list = [e.strip() for e in ext_list]
    return ext_list

def remove_empty_tags(text):
    """Remove empty XML tags from the text."""
    return re.sub(r'\n<(\w+)>\s*</\1>\n', '', text, flags=re.DOTALL)

def strip_last_sentence(text):
    """Strip the last sentence if it starts with 'Let me know'."""
    sentences = text.split('. ')
    if sentences[-1].startswith("Let me know"):
        sentences = sentences[:-1]
        result = '. '.join(sentences)
        if result and not result.endswith('.'):
            result += '.'
        return result
    else:
        return text

def extract_prompt(metaprompt_response):
    """Extract the prompt from the metaprompt response."""
    between_tags = extract_between_tags("Instructions", metaprompt_response)[0]
    return between_tags[:1000] + strip_last_sentence(remove_empty_tags(remove_empty_tags(between_tags[1000:]).strip()).strip())

def extract_variables(prompt):
    """Extract variables from the prompt."""
    pattern = r'{([^}]+)}'
    variables = re.findall(pattern, prompt)
    return set(variables)

def pretty_print(message):
    """Print the message in a formatted way."""
    print('\n\n'.join('\n'.join(line.strip() for line in re.findall(r'.{1,100}(?:\s+|$)', paragraph.strip('\n'))) for paragraph in re.split(r'\n\n+', message)))

def generate_prompt(client, model_name, metaprompt, task):
    """Generate a prompt using the Anthropic API."""
    prompt = metaprompt.replace("{TASK}}", task)
    assistant_partial = "<Inputs>"

    try:
        message = client.messages.create(
            model=model_name,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt
                },
                {
                    "role": "assistant",
                    "content": assistant_partial
                }
            ],
            temperature=0
        ).content[0].text
    except anthropic.APIError as e:
        print(f"Error calling Anthropic API: {e}")
        sys.exit(1)

    return message

def get_large_input(prompt):
    """Open a text editor in a new Gnome terminal for large text input."""
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as temp_file:
        temp_file.write(f"# {prompt}\n# Write your input below this line.\n# Save and close the editor when you're done.\n\n")
        temp_file_path = temp_file.name

    editor = os.environ.get('EDITOR', 'nano')  # Use nano as default if EDITOR is not set
    subprocess.run(['gnome-terminal', '--', editor, temp_file_path])

    input("Press Enter when you've finished editing...")

    with open(temp_file_path, 'r') as file:
        content = file.read()

    os.unlink(temp_file_path)  # Delete the temporary file

    # Remove comments and leading/trailing whitespace
    lines = content.split('\n')
    return '\n'.join(line.strip() for line in lines if not line.strip().startswith('#') and line.strip())

import time
import os

def wait_for_file_modification(file_path, timeout=300):
    """Wait for the file to be modified, with a timeout."""
    start_time = time.time()
    last_modified = os.path.getmtime(file_path)
    
    while time.time() - start_time < timeout:
        time.sleep(1)  # Check every second
        current_modified = os.path.getmtime(file_path)
        if current_modified > last_modified:
            return True
    return False
def main():
    # Read API key and metaprompt
    ANTHROPIC_API_KEY = read_file('ANTHROPIC_API_KEY.txt')
    print(f"API Key: {ANTHROPIC_API_KEY[:10]}...")  # Print first 10 characters of the key
    metaprompt = read_file('metaprompt.txt')

    MODEL_NAME = "claude-3-5-sonnet-20240620"
    CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # Prompt user for task
    print("Please enter your task (press Enter twice when finished):")
    task_lines = []
    while True:
        line = input()
        if line:
            task_lines.append(line)
        else:
            break
    task = ' '.join(task_lines)

    # Generate prompt
    message = generate_prompt(CLIENT, MODEL_NAME, metaprompt, task)

    # Extract prompt and variables
    extracted_prompt_template = extract_prompt(message)
    variables = extract_variables(message)

    # Save variables and prompt to variables_prompt.txt
    variables_prompt_content = f"Variables:\n{', '.join(variables)}\n\nPrompt:\n{extracted_prompt_template}"
    write_file('variables_prompt.txt', variables_prompt_content)

    # Print the initial API response to the screen
    print("\nInitial API Response:")
    pretty_print(message)

    # Prepare the content for the gnome-terminal
    variable_input_content = "\n".join([f"<{var}>\n\n</{var}>" for var in variables])
    
    # Write the variable input content to a temporary file
    with tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.txt') as temp_file:
        temp_file.write(variable_input_content)
        temp_file_path = temp_file.name

    # Open gnome-terminal with the prepared content
    editor = os.environ.get('EDITOR', 'nano')
    subprocess.Popen(['gnome-terminal', '--', editor, temp_file_path])

    # Prompt user to enter variables in the other terminal
    print("\nPlease enter the values for the variables in the other terminal.")
    print("Save the file and close the editor when you're done.")

    # Wait for the file to be modified
    if wait_for_file_modification(temp_file_path):
        print("File has been saved. Processing input...")
    else:
        print("Timeout waiting for file modification. Using last saved version.")

    # Read the entered values from the temporary file
    with open(temp_file_path, 'r') as file:
        entered_content = file.read()

    # Parse the entered content
    entered_variables = {}
    for var in variables:
        match = re.search(f"<{var}>(.*?)</{var}>", entered_content, re.DOTALL)
        if match:
            entered_variables[var] = match.group(1).strip()

    # Replace variables in prompt
    prompt_with_variables = extracted_prompt_template
    for variable, value in entered_variables.items():
        prompt_with_variables = prompt_with_variables.replace("{" + variable + "}", value)

    # Save prompt with inputted variables
    write_file('inputed_variables_prompt.txt', prompt_with_variables)

    # Clean up the temporary file
    os.unlink(temp_file_path)

    # Send final API request
    try:
        response = CLIENT.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": prompt_with_variables
                },
            ],
        ).content[0].text

        # Print response to terminal
        print("\nClaude's output:")
        pretty_print(response)
        print("\nScript execution completed.")

    except anthropic.APIError as e:
        print(f"Error calling Anthropic API: {e}")

if __name__ == "__main__":
    main()
