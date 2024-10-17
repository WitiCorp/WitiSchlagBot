# Use an official Python runtime as a parent image
FROM continuumio/miniconda3

# Set the working directory in the container
WORKDIR /usr/src/app/src

# Copy the environment.yml file into the container
COPY environment.yml /usr/src/app/

# Install the dependencies specified in environment.yml
RUN conda env create -f /usr/src/app/environment.yml

# Make RUN commands use the new environment
SHELL ["conda", "run", "-n", "witi", "/bin/bash", "-c"]

# Copy the current directory contents into the container at /usr/src/app
COPY environment.yml /usr/src/app/
COPY src /usr/src/app/src
RUN rm -rf /usr/src/app/src/Witi*

# Make port 80 available to the world outside this container
EXPOSE 80

# Define environment variable
ENV NAME=MensaBot

# Run bot.py when the container launches
CMD ["conda", "run", "-n", "witi", "python", "./mensa_bot.py"]